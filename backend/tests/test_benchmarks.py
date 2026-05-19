"""Tests for dictation benchmark endpoints."""

from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.transcript_utils import TranscriptResult


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
async def test_dictation_benchmark_battle_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/benchmarks/dictation/battle",
        files={"audio": ("sample.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 401


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
