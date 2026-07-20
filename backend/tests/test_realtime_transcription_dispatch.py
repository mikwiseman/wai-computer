"""Tests covering realtime transcription session dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.core.realtime_transcription import create_realtime_transcription_session

DEEPGRAM_REALTIME_MODEL = "nova-3"
OPENAI_REALTIME_MODEL = "gpt-realtime-whisper"


def _patch_deepgram_key(monkeypatch: pytest.MonkeyPatch) -> Mock:
    check = Mock(return_value="provider_key")
    monkeypatch.setattr(
        "app.core.realtime_transcription.require_deepgram_api_key",
        check,
    )
    return check


def _patch_openai_key(monkeypatch: pytest.MonkeyPatch) -> Mock:
    check = Mock(return_value="provider_key")
    monkeypatch.setattr(
        "app.core.realtime_transcription.require_openai_api_key",
        check,
    )
    return check


def _make_user(
    *,
    dictation_provider="removed-live-provider",
    dictation_model="removed-live-model",
    recording_provider="removed-live-provider",
    recording_model="removed-live-model",
):
    return SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        dictation_live_stt_provider=dictation_provider,
        dictation_live_stt_model=dictation_model,
        recording_live_stt_provider=recording_provider,
        recording_live_stt_model=recording_model,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("legacy-live", "legacy-model"),
        ("deepgram", DEEPGRAM_REALTIME_MODEL),
    ],
)
async def test_dispatch_dictation_ignores_saved_model_and_uses_openai(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
) -> None:
    user = _make_user(
        dictation_provider=provider,
        dictation_model=model,
    )
    check = _patch_openai_key(monkeypatch)

    session = await create_realtime_transcription_session(
        purpose="dictation", user=user,
    )

    assert session.provider == "openai"
    assert session.model == OPENAI_REALTIME_MODEL
    assert session.auth_scheme == "bearer"
    assert session.sample_rate == 24_000
    assert session.channels == 1
    assert session.keep_alive_interval_seconds is None
    assert session.commit_strategy == "manual"
    check.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("legacy-live", "legacy-model"),
        ("deepgram", DEEPGRAM_REALTIME_MODEL),
    ],
)
async def test_dispatch_recording_ignores_saved_model_and_uses_deepgram(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
) -> None:
    user = _make_user(
        recording_provider=provider,
        recording_model=model,
    )
    _patch_deepgram_key(monkeypatch)

    session = await create_realtime_transcription_session(
        purpose="recording", user=user, channels=2,
    )

    assert session.provider == "deepgram"
    assert session.model == DEEPGRAM_REALTIME_MODEL
    assert session.auth_scheme == "bearer"
    assert session.channels == 1


@pytest.mark.asyncio
async def test_dispatch_recording_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_deepgram_key(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="recording", user=None,
    )

    assert session.provider == "deepgram"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_dispatch_dictation_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_openai_key(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="dictation", user=None,
    )

    assert session.provider == "openai"
    assert session.model == OPENAI_REALTIME_MODEL
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_resolved_language_lower_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_deepgram_key(monkeypatch)

    session = await create_realtime_transcription_session(
        language="  EN  ", purpose="recording", user=None,
    )

    assert session.language == "en"
    assert session.language == "en"


@pytest.mark.asyncio
async def test_empty_language_falls_back_to_multi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_deepgram_key(monkeypatch)

    session = await create_realtime_transcription_session(
        language="   ", purpose="recording", user=None,
    )

    assert session.language == "multi"
    assert session.language == "multi"
