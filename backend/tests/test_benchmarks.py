"""Tests for dictation benchmark endpoints."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dictation_benchmark_live import configured_live_benchmark_models
from app.core.transcript_utils import TranscriptResult
from app.models.benchmark import DictationBenchmarkVote


def _settings(**overrides: str) -> SimpleNamespace:
    defaults = {
        "elevenlabs_api_key": "",
        "openai_api_key": "",
        "deepgram_api_key": "",
        "inworld_api_key": "",
        "soniox_api_key": "",
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
        ("soniox", "stt-async-v4"),
    }
    assert {(provider, model) for provider, model in calls} == {
        ("elevenlabs", "scribe_v2"),
        ("soniox", "stt-async-v4"),
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
            "selected_provider": "Soniox",
            "selected_model": "stt-async-v4",
            "language": " RU ",
            "candidate_count": 3,
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
    assert vote.selected_provider == "soniox"
    assert vote.selected_model == "stt-async-v4"
    assert vote.language == "ru"
    assert vote.candidate_count == 3
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
            "selected_provider": "Soniox",
            "selected_model": "stt-async-v4",
            "language": "multi",
            "candidate_count": 3,
        },
    )

    assert response.status_code == 200
    vote_id = UUID(response.json()["vote_id"])

    result = await db_session.execute(
        select(DictationBenchmarkVote).where(DictationBenchmarkVote.id == vote_id)
    )
    vote = result.scalar_one()
    assert vote.user_id is None
    assert vote.selected_provider == "soniox"


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
            "selected_provider": "deepgram",
            "selected_model": "flux-general-multi",
            "language": "ru",
            "candidate_count": 3,
        },
    )

    assert response.status_code == 200
    vote_id = UUID(response.json()["vote_id"])
    result = await db_session.execute(
        select(DictationBenchmarkVote).where(DictationBenchmarkVote.id == vote_id)
    )
    vote = result.scalar_one()
    assert vote.selected_provider == "deepgram"
    assert vote.selected_model == "flux-general-multi"


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

    assert [(model.provider, model.model) for model in models] == [
        ("elevenlabs", "scribe_v2_realtime"),
        ("soniox", "stt-rt-v4"),
        ("deepgram", "flux-general-multi"),
    ]
