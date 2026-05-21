"""Tests for dictation benchmark endpoints."""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from app.api.routes.benchmarks import create_live_dictation_benchmark_battle
from app.core import dictation_benchmark_live as live_benchmark
from app.core.dictation_benchmark_live import (
    LiveBenchmarkModel,
    LiveBenchmarkProviderRunner,
    configured_live_benchmark_models,
)
from app.core.transcript_utils import TranscriptResult
from app.models.benchmark import DictationBenchmarkVote


def _settings(**overrides: str) -> SimpleNamespace:
    defaults = {
        "elevenlabs_api_key": "",
        "openai_api_key": "",
        "deepgram_api_key": "",
        "inworld_api_key": "",
        "soniox_api_key": "",
        "elevenlabs_no_verbatim": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_dictation_benchmark_battle_runs_for_anonymous_visitors(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.api.routes.benchmarks.get_settings",
        lambda: _settings(elevenlabs_api_key="xi"),
    )

    async def fake_transcribe_audio_file(*args, **kwargs):
        return [
            TranscriptResult(
                text="anonymous transcript",
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=1000,
                confidence=0.9,
            )
        ]

    monkeypatch.setattr(
        "app.api.routes.benchmarks.transcribe_audio_file",
        fake_transcribe_audio_file,
    )

    response = await client.post(
        "/api/benchmarks/dictation/battle",
        files={"audio": ("sample.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["candidates"][0]["transcript"] == "anonymous transcript"


@pytest.mark.asyncio
async def test_dictation_benchmark_battle_runs_configured_file_providers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.api.routes.benchmarks.get_settings",
        lambda: _settings(elevenlabs_api_key="xi", soniox_api_key="sx"),
    )
    calls: list[tuple[str, str]] = []

    async def fake_transcribe_audio_file(*args, **kwargs):
        provider = kwargs["provider"]
        model = kwargs["model"]
        calls.append((provider, model))
        return [
            TranscriptResult(
                text=f"{provider} transcript",
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=1000,
                confidence=0.9,
            )
        ]

    monkeypatch.setattr(
        "app.api.routes.benchmarks.transcribe_audio_file",
        fake_transcribe_audio_file,
    )

    response = await client.post(
        "/api/benchmarks/dictation/battle",
        headers=auth_headers,
        data={"language": "ru"},
        files={"audio": ("sample.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "ru"
    assert {(candidate["provider"], candidate["model"]) for candidate in data["candidates"]} == {
        ("elevenlabs", "scribe_v2"),
    }
    assert {(provider, model) for provider, model in calls} == {
        ("elevenlabs", "scribe_v2"),
    }
    assert all(candidate["status"] == "ok" for candidate in data["candidates"])
    assert all("transcript" in candidate["transcript"] for candidate in data["candidates"])


@pytest.mark.asyncio
async def test_dictation_benchmark_battle_returns_provider_errors_per_candidate(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.api.routes.benchmarks.get_settings",
        lambda: _settings(elevenlabs_api_key="xi"),
    )

    async def fake_transcribe_audio_file(*args, **kwargs):
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(
        "app.api.routes.benchmarks.transcribe_audio_file",
        fake_transcribe_audio_file,
    )

    response = await client.post(
        "/api/benchmarks/dictation/battle",
        headers=auth_headers,
        files={"audio": ("sample.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["candidates"][0]["status"] == "error"
    assert data["candidates"][0]["error"] == "Provider request failed."
    assert data["candidates"][0]["transcript"] is None


@pytest.mark.asyncio
async def test_dictation_benchmark_vote_persists_metadata_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
):
    response = await client.post(
        "/api/benchmarks/dictation/battle/vote",
        headers=auth_headers,
        json={
            "battle_id": "battle-1",
            "selected_candidate_id": "candidate-a",
            "selected_provider": "ElevenLabs",
            "selected_model": "scribe_v2",
            "language": " RU ",
            "candidate_count": 1,
        },
    )

    assert response.status_code == 200
    vote_id = UUID(response.json()["vote_id"])

    result = await db_session.execute(
        select(DictationBenchmarkVote).where(DictationBenchmarkVote.id == vote_id)
    )
    vote = result.scalar_one()
    assert vote.battle_id == "battle-1"
    assert vote.selected_candidate_id == "candidate-a"
    assert vote.selected_provider == "elevenlabs"
    assert vote.selected_model == "scribe_v2"
    assert vote.language == "ru"
    assert vote.candidate_count == 1
    assert vote.user_id is not None


@pytest.mark.asyncio
async def test_dictation_benchmark_vote_accepts_anonymous_visitors(
    client: AsyncClient,
    db_session: AsyncSession,
):
    response = await client.post(
        "/api/benchmarks/dictation/battle/vote",
        json={
            "battle_id": "battle-1",
            "selected_candidate_id": "candidate-a",
            "selected_provider": "ElevenLabs",
            "selected_model": "scribe_v2",
            "language": "multi",
            "candidate_count": 1,
        },
    )

    assert response.status_code == 200
    vote_id = UUID(response.json()["vote_id"])

    result = await db_session.execute(
        select(DictationBenchmarkVote).where(DictationBenchmarkVote.id == vote_id)
    )
    vote = result.scalar_one()
    assert vote.user_id is None
    assert vote.selected_provider == "elevenlabs"


@pytest.mark.asyncio
async def test_dictation_benchmark_vote_accepts_live_models(
    client: AsyncClient,
    db_session: AsyncSession,
):
    response = await client.post(
        "/api/benchmarks/dictation/battle/vote",
        json={
            "battle_id": "live-battle-1",
            "selected_candidate_id": "candidate-c",
            "selected_provider": "inworld",
            "selected_model": "inworld/inworld-stt-1",
            "language": "ru",
            "candidate_count": 1,
        },
    )

    assert response.status_code == 200
    vote_id = UUID(response.json()["vote_id"])
    result = await db_session.execute(
        select(DictationBenchmarkVote).where(DictationBenchmarkVote.id == vote_id)
    )
    vote = result.scalar_one()
    assert vote.selected_provider == "inworld"
    assert vote.selected_model == "inworld/inworld-stt-1"


@pytest.mark.asyncio
async def test_dictation_benchmark_vote_rejects_unsupported_model(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    response = await client.post(
        "/api/benchmarks/dictation/battle/vote",
        headers=auth_headers,
        json={
            "battle_id": "battle-1",
            "selected_candidate_id": "candidate-a",
            "selected_provider": "openai",
            "selected_model": "gpt-4o-transcribe",
            "language": "multi",
            "candidate_count": 3,
        },
    )

    assert response.status_code == 422


def test_configured_live_benchmark_models_uses_live_provider_pool():
    settings = _settings(
        elevenlabs_api_key="xi",
        soniox_api_key="sx",
        deepgram_api_key="dg",
        inworld_api_key="iw",
    )

    models = configured_live_benchmark_models(settings=settings)

    assert models == []


def test_configured_live_benchmark_models_skips_unconfigured_and_unsupported_providers():
    settings = _settings(soniox_api_key="sx")

    models = configured_live_benchmark_models(settings=settings)

    assert models == []
    assert live_benchmark._language_hints(" auto ") == []
    assert live_benchmark._language_for_elevenlabs("multi") == [
        ("include_language_detection", "true")
    ]


@pytest.mark.asyncio
async def test_live_benchmark_receive_loop_treats_upstream_close_as_normal():
    class ClosingUpstream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionClosedError(None, None)

    async def send_event(event: dict):
        raise AssertionError(f"unexpected event: {event}")

    async def handle_message(message: str):
        raise AssertionError(f"unexpected message: {message}")

    runner = LiveBenchmarkProviderRunner(
        battle_id="battle-1",
        candidate=LiveBenchmarkModel(
            id="candidate-1",
            provider="elevenlabs",
            model="scribe_v2_realtime",
            label="ElevenLabs",
        ),
        language="ru",
        settings=_settings(elevenlabs_api_key="xi"),
        send_event=send_event,
    )

    await runner._receive_loop(ClosingUpstream(), handle_message)


@pytest.mark.asyncio
async def test_live_benchmark_deepgram_finalization_sends_silence_then_close_stream():
    class Upstream:
        def __init__(self) -> None:
            self.sent: list[bytes | str] = []

        async def send(self, message: bytes | str) -> None:
            self.sent.append(message)

    async def send_event(event: dict):
        raise AssertionError(f"unexpected event: {event}")

    runner = LiveBenchmarkProviderRunner(
        battle_id="battle-1",
        candidate=LiveBenchmarkModel(
            id="candidate-1",
            provider="deepgram",
            model="flux-general-multi",
            label="Deepgram",
        ),
        language="ru",
        settings=_settings(deepgram_api_key="dg"),
        send_event=send_event,
    )
    upstream = Upstream()

    await runner._send_deepgram_audio(upstream, None)

    assert len(upstream.sent) == 2
    assert isinstance(upstream.sent[0], bytes)
    assert set(upstream.sent[0]) == {0}
    assert upstream.sent[1] == '{"type": "CloseStream"}'


@pytest.mark.asyncio
async def test_dictation_benchmark_battle_rejects_invalid_uploads(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.api.routes.benchmarks.get_settings",
        lambda: _settings(elevenlabs_api_key="xi"),
    )

    unsupported = await client.post(
        "/api/benchmarks/dictation/battle",
        files={"audio": ("sample.txt", b"audio", "text/plain")},
    )
    assert unsupported.status_code == 415

    empty = await client.post(
        "/api/benchmarks/dictation/battle",
        files={"audio": ("sample.webm", b"", "audio/webm")},
    )
    assert empty.status_code == 422

    too_large = await client.post(
        "/api/benchmarks/dictation/battle",
        files={"audio": ("sample.webm", b"x" * (8 * 1024 * 1024 + 1), "audio/webm")},
    )
    assert too_large.status_code == 413


@pytest.mark.asyncio
async def test_dictation_benchmark_battle_requires_configured_file_provider(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("app.api.routes.benchmarks.get_settings", lambda: _settings())

    response = await client.post(
        "/api/benchmarks/dictation/battle",
        files={"audio": ("sample.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "No file transcription providers are configured for benchmark battles."
    )


class _BenchmarkUpstream:
    def __init__(self, messages: list[bytes | str] | None = None) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._messages = list(messages or [])

    async def send(self, message: bytes | str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


class _BenchmarkConnect:
    def __init__(self, upstream: _BenchmarkUpstream) -> None:
        self.upstream = upstream
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self

    async def __aenter__(self):
        return self.upstream

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _runner(
    provider: str,
    *,
    settings: SimpleNamespace | None = None,
    send_event=None,
) -> LiveBenchmarkProviderRunner:
    async def default_send_event(event: dict):
        raise AssertionError(f"unexpected event: {event}")

    return LiveBenchmarkProviderRunner(
        battle_id="battle-1",
        candidate=LiveBenchmarkModel(
            id=f"{provider}-candidate",
            provider=provider,
            model={
                "elevenlabs": "scribe_v2_realtime",
                "soniox": "stt-rt-v4",
                "deepgram": "flux-general-multi",
            }.get(provider, "unknown"),
            label=provider.title(),
        ),
        language=" RU ",
        settings=settings
        or _settings(
            elevenlabs_api_key="xi",
            soniox_api_key="sx",
            deepgram_api_key="dg",
            elevenlabs_no_verbatim=True,
        ),
        send_event=send_event or default_send_event,
    )


@pytest.mark.asyncio
async def test_live_benchmark_runner_opens_provider_connections(
    monkeypatch: pytest.MonkeyPatch,
):
    upstream = _BenchmarkUpstream()
    connector = _BenchmarkConnect(upstream)
    monkeypatch.setattr("app.core.dictation_benchmark_live.websockets.connect", connector)
    pump_calls: list[tuple[str, str]] = []

    async def fake_pump(upstream_arg, send_audio, handle_message):
        assert upstream_arg is upstream
        pump_calls.append((send_audio.__name__, handle_message.__name__))

    elevenlabs = _runner("elevenlabs")
    monkeypatch.setattr(elevenlabs, "_pump", fake_pump)
    await elevenlabs._run_elevenlabs()

    soniox = _runner("soniox")
    monkeypatch.setattr(soniox, "_pump", fake_pump)
    await soniox._run_soniox()

    deepgram = _runner("deepgram")
    monkeypatch.setattr(deepgram, "_pump", fake_pump)
    await deepgram._run_deepgram()

    assert "wss://api.elevenlabs.io/v1/speech-to-text/realtime?" in connector.calls[0][0]
    assert "language_code=ru" in connector.calls[0][0]
    assert "no_verbatim=true" in connector.calls[0][0]
    assert connector.calls[0][1]["additional_headers"] == {"xi-api-key": "xi"}
    assert connector.calls[1][0].startswith("wss://")
    assert json.loads(upstream.sent[0])["api_key"] == "sx"
    assert "language_hints" in json.loads(upstream.sent[0])
    assert "model=flux-general-multi" in connector.calls[2][0]
    assert "language_hint=ru" in connector.calls[2][0]
    assert connector.calls[2][1]["additional_headers"] == {"Authorization": "Token dg"}
    assert pump_calls == [
        ("_send_elevenlabs_audio", "_handle_elevenlabs"),
        ("_send_soniox_audio", "_handle_soniox"),
        ("_send_deepgram_audio", "_handle_deepgram"),
    ]


@pytest.mark.asyncio
async def test_live_benchmark_runner_sends_provider_audio_frames():
    upstream = _BenchmarkUpstream()

    elevenlabs = _runner("elevenlabs")
    await elevenlabs._send_elevenlabs_audio(upstream, b"abc")
    await elevenlabs._send_elevenlabs_audio(upstream, None)
    first_payload = json.loads(upstream.sent[0])
    final_payload = json.loads(upstream.sent[1])
    assert first_payload["audio_base_64"] == "YWJj"
    assert first_payload["commit"] is False
    assert final_payload["commit"] is True
    assert final_payload["sample_rate"] == 16_000

    soniox = _runner("soniox")
    upstream.sent.clear()
    await soniox._send_soniox_audio(upstream, b"pcm")
    await soniox._send_soniox_audio(upstream, None)
    assert upstream.sent[0] == b"pcm"
    assert isinstance(upstream.sent[1], bytes)
    assert json.loads(upstream.sent[2]) == {"type": "finalize"}
    assert upstream.sent[3] == ""

    deepgram = _runner("deepgram")
    upstream.sent.clear()
    await deepgram._send_deepgram_audio(upstream, b"pcm")
    assert upstream.sent == [b"pcm"]


@pytest.mark.asyncio
async def test_live_benchmark_runner_normalizes_provider_events():
    events: list[dict] = []

    async def send_event(event: dict):
        events.append(event)

    elevenlabs = _runner("elevenlabs", send_event=send_event)
    await elevenlabs._handle_elevenlabs("not json")
    await elevenlabs._handle_elevenlabs(
        json.dumps({"message_type": "partial_transcript", "text": "hello"})
    )
    await elevenlabs._handle_elevenlabs(
        json.dumps({"message_type": "committed_transcript", "text": "hello world"})
    )
    with pytest.raises(RuntimeError, match="bad"):
        await elevenlabs._handle_elevenlabs(
            json.dumps({"message_type": "provider_error", "message": "bad"})
        )

    soniox = _runner("soniox", send_event=send_event)
    await soniox._handle_soniox(json.dumps({"tokens": "ignored"}))
    await soniox._handle_soniox(
        json.dumps(
            {
                "tokens": [
                    {"text": "final ", "is_final": True},
                    {"text": "partial", "is_final": False},
                    {"text": "<noise>", "is_final": False},
                    {"text": "ignored", "is_final": False, "translation_status": "translation"},
                ]
            }
        )
    )
    with pytest.raises(RuntimeError, match="sx failed"):
        await soniox._handle_soniox(
            json.dumps({"error_code": "E_BAD", "error_message": "sx failed"})
        )

    deepgram = _runner("deepgram", send_event=send_event)
    await deepgram._handle_deepgram(json.dumps({"type": "TurnInfo", "transcript": ""}))
    await deepgram._handle_deepgram(
        json.dumps({"type": "TurnInfo", "event": "EndOfTurn", "transcript": "done"})
    )
    await deepgram._handle_deepgram(json.dumps({"type": "Results", "channel": {}}))
    await deepgram._handle_deepgram(
        json.dumps(
            {
                "type": "Results",
                "is_final": True,
                "channel": {"alternatives": [{"transcript": "result text"}]},
            }
        )
    )
    with pytest.raises(RuntimeError, match="dg failed"):
        await deepgram._handle_deepgram(json.dumps({"type": "Error", "description": "dg failed"}))

    transcripts = [
        event["candidate"]["transcript"]
        for event in events
        if event["type"] == "candidate_update"
    ]
    assert transcripts == [
        "hello",
        "hello world",
        "final",
        "final partial",
        "done",
        "done result text",
    ]
    assert events[-1]["candidate"]["word_count"] == 3


@pytest.mark.asyncio
async def test_live_benchmark_runner_completion_and_error_events():
    events: list[dict] = []

    async def send_event(event: dict):
        events.append(event)

    runner = _runner("elevenlabs", send_event=send_event)
    await runner._emit_status("running")
    await runner._emit_completion()
    await runner._emit_transcript("same text", final=True, append=True)
    await runner._emit_transcript("same text", final=True, append=True)
    await runner._emit_completion()

    assert events[0]["type"] == "candidate_status"
    assert events[1]["type"] == "candidate_error"
    assert events[1]["candidate"]["error"] == "No live transcript returned."
    assert [event["type"] for event in events[2:]] == ["candidate_update", "candidate_update"]
    assert events[-1]["is_final"] is True


@pytest.mark.asyncio
async def test_live_benchmark_runner_run_reports_provider_failures():
    events: list[dict] = []

    async def send_event(event: dict):
        events.append(event)

    runner = _runner("elevenlabs", settings=_settings(), send_event=send_event)

    await runner.run()

    assert events[0]["type"] == "candidate_status"
    assert events[1]["type"] == "candidate_error"
    assert events[1]["candidate"]["status"] == "error"
    assert events[1]["candidate"]["error"] == "Provider live stream failed."


@pytest.mark.asyncio
async def test_live_benchmark_runner_enqueue_finish_and_run_branches(monkeypatch):
    events: list[dict] = []

    async def send_event(event: dict):
        events.append(event)

    soniox = _runner("soniox", send_event=send_event)

    async def fake_soniox_stream():
        await soniox._emit_transcript("soniox final", final=True, append=True)

    monkeypatch.setattr(soniox, "_run_soniox", fake_soniox_stream)
    await soniox.enqueue_audio(b"pcm")
    await soniox.finish()
    assert await soniox.queue.get() == b"pcm"
    assert await soniox.queue.get() is None
    await soniox.run()

    deepgram = _runner("deepgram", send_event=send_event)

    async def fake_deepgram_stream():
        await deepgram._emit_transcript("deepgram final", final=True, append=True)

    monkeypatch.setattr(deepgram, "_run_deepgram", fake_deepgram_stream)
    await deepgram.run()

    unsupported = _runner("unknown", send_event=send_event)
    await unsupported.run()

    assert [event["type"] for event in events].count("candidate_status") == 3
    assert any(
        event["candidate"]["transcript"] == "soniox final"
        for event in events
        if event["type"] == "candidate_update"
    )
    assert any(
        event["candidate"]["transcript"] == "deepgram final"
        for event in events
        if event["type"] == "candidate_update"
    )
    assert events[-1]["type"] == "candidate_error"


@pytest.mark.asyncio
async def test_live_benchmark_runner_provider_methods_require_keys():
    with pytest.raises(RuntimeError, match="SONIOX_API_KEY not configured"):
        await _runner("soniox", settings=_settings())._run_soniox()

    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY not configured"):
        await _runner("deepgram", settings=_settings())._run_deepgram()


@pytest.mark.asyncio
async def test_live_benchmark_pump_waits_for_final_messages_then_closes():
    runner = _runner("deepgram")

    class HangingUpstream(_BenchmarkUpstream):
        async def __anext__(self):
            await asyncio.sleep(60)
            raise StopAsyncIteration

    upstream = HangingUpstream()
    runner._finalization_wait_seconds = lambda: 0.01

    async def send_audio(upstream_arg, chunk):
        await upstream_arg.send(chunk or b"final")

    async def never_finishes(_message: str):
        raise AssertionError("receive loop should not handle messages")

    runner.queue.put_nowait(None)

    await runner._pump(upstream, send_audio, never_finishes)

    assert upstream.sent == [b"final"]
    assert upstream.closed is True


@pytest.mark.asyncio
async def test_live_benchmark_pump_returns_when_receive_loop_finishes():
    runner = _runner("elevenlabs")
    upstream = _BenchmarkUpstream(messages=['{"ok": true}'])
    handled: list[str] = []

    async def send_audio(upstream_arg, chunk):
        await asyncio.sleep(60)

    async def handle_message(message: str):
        handled.append(message)

    await runner._pump(upstream, send_audio, handle_message)

    assert handled == ['{"ok": true}']


@pytest.mark.asyncio
async def test_live_benchmark_receive_loop_decodes_text_bytes_and_ignores_bad_utf8():
    runner = _runner("elevenlabs")
    upstream = _BenchmarkUpstream(messages=[b'{"type":"partial"}', b"\xff"])
    handled: list[str] = []

    async def handle_message(message: str):
        handled.append(message)

    await runner._receive_loop(upstream, handle_message)

    assert handled == ['{"type":"partial"}']


@pytest.mark.asyncio
async def test_live_benchmark_handlers_ignore_malformed_or_empty_provider_payloads():
    events: list[dict] = []

    async def send_event(event: dict):
        events.append(event)

    runner = _runner("soniox", send_event=send_event)
    await runner._emit_transcript("   ", final=True, append=True)
    await runner._handle_soniox("not-json")
    await runner._handle_soniox(
        json.dumps(
            {
                "tokens": [
                    "not-a-token",
                    {"text": "", "is_final": True},
                ]
            }
        )
    )

    deepgram = _runner("deepgram", send_event=send_event)
    await deepgram._handle_deepgram("not-json")

    assert events == []


def test_live_benchmark_finalization_wait_is_longer_for_deepgram():
    assert _runner("deepgram")._finalization_wait_seconds() == (
        live_benchmark.DEEPGRAM_FINALIZATION_WAIT_SECONDS
    )
    assert _runner("elevenlabs")._finalization_wait_seconds() == (
        live_benchmark.FINALIZATION_WAIT_SECONDS
    )


class _LiveBenchmarkWebSocket:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.client = SimpleNamespace(host="127.0.0.1")
        self.sent: list[dict] = []
        self.close_codes: list[int | None] = []
        self.accepted = False
        self._messages = list(messages or [])

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int | None = None) -> None:
        self.close_codes.append(code)

    async def receive(self) -> dict:
        if not self._messages:
            raise WebSocketDisconnect()
        next_message = self._messages.pop(0)
        if next_message.get("disconnect"):
            raise WebSocketDisconnect()
        return next_message


@pytest.mark.asyncio
async def test_live_benchmark_route_closes_when_rate_limited(monkeypatch: pytest.MonkeyPatch):
    websocket = _LiveBenchmarkWebSocket()

    def reject(_websocket):
        raise HTTPException(status_code=429)

    monkeypatch.setattr("app.api.routes.benchmarks._check_benchmark_rate_limit", reject)

    await create_live_dictation_benchmark_battle(websocket)

    assert websocket.accepted is False
    assert websocket.close_codes == [1008]


@pytest.mark.asyncio
async def test_live_benchmark_route_reports_missing_realtime_providers(
    monkeypatch: pytest.MonkeyPatch,
):
    websocket = _LiveBenchmarkWebSocket()
    monkeypatch.setattr(
        "app.api.routes.benchmarks.configured_live_benchmark_models",
        lambda **_: [],
    )

    await create_live_dictation_benchmark_battle(websocket)

    assert websocket.accepted is True
    assert websocket.sent == [
        {
            "type": "battle_error",
            "message": "No realtime transcription providers are configured.",
        }
    ]
    assert websocket.close_codes == [1011]


@pytest.mark.asyncio
async def test_live_benchmark_route_fans_out_audio_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
):
    websocket = _LiveBenchmarkWebSocket(
        [
            {"bytes": b"pcm"},
            {"bytes": b""},
            {"text": "not json"},
            {"text": json.dumps({"type": "finish"})},
        ]
    )
    model = LiveBenchmarkModel(
        id="candidate-1",
        provider="elevenlabs",
        model="scribe_v2_realtime",
        label="ElevenLabs",
    )
    monkeypatch.setattr(
        "app.api.routes.benchmarks.configured_live_benchmark_models",
        lambda **_: [model],
    )
    instances: list[object] = []

    class FakeRunner:
        def __init__(self, *, battle_id, candidate, language, settings, send_event):
            self.battle_id = battle_id
            self.candidate = candidate
            self.language = language
            self.send_event = send_event
            self.audio: list[bytes] = []
            self.finished = False
            instances.append(self)

        async def run(self):
            await self.send_event(
                {
                    "type": "candidate_update",
                    "battle_id": self.battle_id,
                    "is_final": True,
                    "candidate": {
                        "id": self.candidate.id,
                        "provider": self.candidate.provider,
                        "model": self.candidate.model,
                        "label": self.candidate.label,
                        "status": "ok",
                        "transcript": "hello",
                        "latency_ms": 1,
                        "word_count": 1,
                        "error": None,
                    },
                }
            )

        async def enqueue_audio(self, chunk: bytes):
            self.audio.append(chunk)

        async def finish(self):
            self.finished = True

    monkeypatch.setattr("app.api.routes.benchmarks.LiveBenchmarkProviderRunner", FakeRunner)

    await create_live_dictation_benchmark_battle(websocket, language=" RU ")

    assert websocket.accepted is True
    assert websocket.sent[0]["type"] == "battle_started"
    assert websocket.sent[0]["language"] == "ru"
    assert websocket.sent[1]["type"] == "candidate_update"
    assert websocket.sent[-1]["type"] == "battle_finished"
    assert websocket.close_codes == [None]
    assert instances[0].audio == [b"pcm"]
    assert instances[0].finished is True


@pytest.mark.asyncio
async def test_live_benchmark_route_skips_final_close_after_client_disconnect(
    monkeypatch: pytest.MonkeyPatch,
):
    websocket = _LiveBenchmarkWebSocket([{"disconnect": True}])
    model = LiveBenchmarkModel(
        id="candidate-1",
        provider="soniox",
        model="stt-rt-v4",
        label="Soniox",
    )
    monkeypatch.setattr(
        "app.api.routes.benchmarks.configured_live_benchmark_models",
        lambda **_: [model],
    )
    finished: list[bool] = []

    class FakeRunner:
        def __init__(self, **kwargs):
            pass

        async def run(self):
            return None

        async def enqueue_audio(self, chunk: bytes):
            raise AssertionError(f"unexpected audio: {chunk!r}")

        async def finish(self):
            finished.append(True)

    monkeypatch.setattr("app.api.routes.benchmarks.LiveBenchmarkProviderRunner", FakeRunner)

    await create_live_dictation_benchmark_battle(websocket)

    assert finished == [True]
    assert websocket.sent[0]["type"] == "battle_started"
    assert websocket.close_codes == []
