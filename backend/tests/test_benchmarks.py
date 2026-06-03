"""Tests for dictation benchmark endpoints after provider lock-down."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import benchmarks
from app.api.routes.benchmarks import (
    DictationBenchmarkCandidate,
    DictationBenchmarkVoteRequest,
)


def test_configured_file_stt_options_returns_only_deepgram_when_configured(monkeypatch):
    monkeypatch.setattr(
        benchmarks,
        "get_settings",
        lambda: SimpleNamespace(
            deepgram_api_key="configured-for-test",
            elevenlabs_api_key="",
            openai_api_key="configured-for-test",
        ),
    )

    options = benchmarks._configured_file_stt_options()

    assert [(option.provider, option.model) for option in options] == [
        ("deepgram", "nova-3")
    ]


def test_benchmark_router_has_no_realtime_provider_battle_route():
    route_paths = {getattr(route, "path", None) for route in benchmarks.router.routes}

    assert "/benchmarks/dictation/live-battle" not in route_paths


def test_check_benchmark_rate_limit_uses_client_ip(monkeypatch):
    limiter = _Limiter()
    monkeypatch.setattr(benchmarks, "get_rate_limiter", lambda: limiter)

    benchmarks._check_benchmark_rate_limit(
        SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))
    )

    assert limiter.calls == [
        {
            "key": "dictation_benchmark:1.2.3.4",
            "max_requests": benchmarks.BENCHMARK_RATE_LIMIT_REQUESTS,
            "window_seconds": benchmarks.BENCHMARK_RATE_LIMIT_WINDOW_SECONDS,
        }
    ]


@pytest.mark.asyncio
async def test_transcribe_candidate_returns_transcript_metadata(monkeypatch):
    async def fake_transcribe_audio_file(*args, **kwargs):
        del args, kwargs
        return [
            SimpleNamespace(text=" hello "),
            SimpleNamespace(text="world"),
            SimpleNamespace(text="  "),
        ]

    monkeypatch.setattr(benchmarks, "transcribe_audio_file", fake_transcribe_audio_file)

    candidate = await benchmarks._transcribe_candidate(
        audio_data=b"audio",
        content_type="audio/wav",
        language="ru",
        provider="deepgram",
        model="nova-3",
        label="Deepgram Nova-3",
    )

    assert candidate.status == "ok"
    assert candidate.transcript == "hello world"
    assert candidate.word_count == 2
    assert candidate.provider == "deepgram"
    assert candidate.model == "nova-3"


@pytest.mark.asyncio
async def test_transcribe_candidate_returns_generic_provider_error(monkeypatch):
    async def fake_transcribe_audio_file(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(benchmarks, "transcribe_audio_file", fake_transcribe_audio_file)

    candidate = await benchmarks._transcribe_candidate(
        audio_data=b"audio",
        content_type="audio/wav",
        language="multi",
        provider="deepgram",
        model="nova-3",
        label="Deepgram Nova-3",
    )

    assert candidate.status == "error"
    assert candidate.error == "Provider request failed."
    assert candidate.transcript is None


@pytest.mark.asyncio
async def test_create_dictation_benchmark_battle_runs_configured_file_stt(monkeypatch):
    monkeypatch.setattr(benchmarks, "_check_benchmark_rate_limit", lambda request: None)
    monkeypatch.setattr(
        benchmarks,
        "_configured_file_stt_options",
        lambda: [
            SimpleNamespace(
                provider="deepgram",
                model="nova-3",
                label="Deepgram Nova-3",
            )
        ],
    )

    async def fake_transcribe_candidate(**kwargs):
        assert kwargs["audio_data"] == b"audio"
        assert kwargs["content_type"] == "audio/wav"
        assert kwargs["language"] == "ru"
        return DictationBenchmarkCandidate(
            id="candidate-1",
            provider=kwargs["provider"],
            model=kwargs["model"],
            label=kwargs["label"],
            status="ok",
            transcript="Привет",
            latency_ms=12,
            word_count=1,
        )

    monkeypatch.setattr(benchmarks, "_transcribe_candidate", fake_transcribe_candidate)

    response = await benchmarks.create_dictation_benchmark_battle(
        request=SimpleNamespace(client=None),
        user=None,
        audio=_Upload(content=b"audio", content_type="audio/wav; codecs=pcm"),
        language=" RU ",
    )

    assert response.language == "ru"
    assert len(response.candidates) == 1
    assert response.candidates[0].provider == "deepgram"
    assert response.candidates[0].model == "nova-3"


@pytest.mark.asyncio
async def test_create_dictation_benchmark_battle_rejects_bad_audio(monkeypatch):
    monkeypatch.setattr(benchmarks, "_check_benchmark_rate_limit", lambda request: None)

    with pytest.raises(HTTPException) as exc_info:
        await benchmarks.create_dictation_benchmark_battle(
            request=SimpleNamespace(client=None),
            user=None,
            audio=_Upload(content=b"audio", content_type="text/plain"),
        )

    assert exc_info.value.status_code == 415

    with pytest.raises(HTTPException) as empty_info:
        await benchmarks.create_dictation_benchmark_battle(
            request=SimpleNamespace(client=None),
            user=None,
            audio=_Upload(content=b"", content_type="audio/wav"),
        )

    assert empty_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_dictation_benchmark_battle_rejects_oversized_audio(monkeypatch):
    monkeypatch.setattr(benchmarks, "_check_benchmark_rate_limit", lambda request: None)

    with pytest.raises(HTTPException) as exc_info:
        await benchmarks.create_dictation_benchmark_battle(
            request=SimpleNamespace(client=None),
            user=None,
            audio=_Upload(
                content=b"x" * (benchmarks.MAX_BENCHMARK_AUDIO_BYTES + 1),
                content_type="audio/wav",
            ),
        )

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_create_dictation_benchmark_battle_requires_configured_file_stt(monkeypatch):
    monkeypatch.setattr(benchmarks, "_check_benchmark_rate_limit", lambda request: None)
    monkeypatch.setattr(benchmarks, "_configured_file_stt_options", lambda: [])

    with pytest.raises(HTTPException) as exc_info:
        await benchmarks.create_dictation_benchmark_battle(
            request=SimpleNamespace(client=None),
            user=None,
            audio=_Upload(content=b"audio", content_type="audio/wav"),
        )

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_create_dictation_benchmark_vote_persists_normalized_choice():
    db = _DB()
    user_id = uuid4()
    request = DictationBenchmarkVoteRequest(
        battle_id="battle-1",
        selected_candidate_id="candidate-1",
        selected_provider=" DeepGram ",
        selected_model=" nova-3 ",
        language=" RU ",
        candidate_count=1,
    )

    response = await benchmarks.create_dictation_benchmark_vote(
        request=request,
        user=SimpleNamespace(id=user_id),
        db=db,
    )

    assert db.committed
    assert db.added is not None
    assert db.added.user_id == user_id
    assert db.added.selected_provider == "deepgram"
    assert db.added.selected_model == "nova-3"
    assert db.added.language == "ru"
    assert response.vote_id == str(db.added.id)


@pytest.mark.asyncio
async def test_create_dictation_benchmark_vote_rejects_removed_stt_option():
    request = DictationBenchmarkVoteRequest(
        battle_id="battle-1",
        selected_candidate_id="candidate-1",
        selected_provider="removed",
        selected_model="removed-model",
        language="multi",
        candidate_count=1,
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmarks.create_dictation_benchmark_vote(
            request=request,
            user=None,
            db=_DB(),
        )

    assert exc_info.value.status_code == 422


class _Upload:
    def __init__(self, *, content: bytes, content_type: str):
        self._content = content
        self.content_type = content_type

    async def read(self, limit: int) -> bytes:
        return self._content[:limit]


class _Limiter:
    def __init__(self):
        self.calls = []

    def check(self, **kwargs):
        self.calls.append(kwargs)


class _DB:
    def __init__(self):
        self.added = None
        self.committed = False

    def add(self, item):
        self.added = item

    async def commit(self):
        self.committed = True
