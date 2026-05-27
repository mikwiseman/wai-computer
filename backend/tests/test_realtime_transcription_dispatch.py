"""Tests covering realtime transcription session dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.core.realtime_transcription import create_realtime_transcription_session

OPENAI_REALTIME_MODEL = "gpt-realtime-whisper"


def _patch_openai_mint(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mint = AsyncMock(return_value="ek_openai")
    monkeypatch.setattr(
        "app.core.realtime_transcription.create_realtime_client_secret",
        mint,
    )
    return mint


def _make_user(
    *,
    dictation_provider="elevenlabs",
    dictation_model="scribe_v2_realtime",
    recording_provider="elevenlabs",
    recording_model="scribe_v2_realtime",
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
        ("elevenlabs", "scribe_v2_realtime"),
        ("deepgram", "flux-general-multi"),
        ("soniox", "stt-rt-v4"),
        ("legacy-live", "legacy-model"),
        ("openai", OPENAI_REALTIME_MODEL),
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
    mint = _patch_openai_mint(monkeypatch)

    session = await create_realtime_transcription_session(
        purpose="dictation", user=user,
    )

    assert session.provider == "openai"
    assert session.model == OPENAI_REALTIME_MODEL
    assert session.auth_scheme == "bearer"
    assert session.sample_rate == 24_000
    assert session.channels == 1
    mint.assert_awaited_once_with(model=OPENAI_REALTIME_MODEL, language="multi")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("elevenlabs", "scribe_v2_realtime"),
        ("deepgram", "nova-3"),
        ("soniox", "stt-rt-v4"),
        ("legacy-live", "legacy-model"),
        ("openai", OPENAI_REALTIME_MODEL),
    ],
)
async def test_dispatch_recording_ignores_saved_model_and_uses_openai(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
) -> None:
    user = _make_user(
        recording_provider=provider,
        recording_model=model,
    )
    _patch_openai_mint(monkeypatch)

    session = await create_realtime_transcription_session(
        purpose="recording", user=user, channels=2,
    )

    assert session.provider == "openai"
    assert session.model == OPENAI_REALTIME_MODEL
    assert session.auth_scheme == "bearer"
    assert session.channels == 1


@pytest.mark.asyncio
async def test_dispatch_recording_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_openai_mint(monkeypatch)
    session = await create_realtime_transcription_session(
        purpose="recording", user=None,
    )

    assert session.provider == "openai"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_dispatch_dictation_with_no_user_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_openai_mint(monkeypatch)
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
    mint = _patch_openai_mint(monkeypatch)

    session = await create_realtime_transcription_session(
        language="  EN  ", purpose="recording", user=None,
    )

    assert session.language == "en"
    mint.assert_awaited_once_with(model=OPENAI_REALTIME_MODEL, language="en")


@pytest.mark.asyncio
async def test_empty_language_falls_back_to_multi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_openai_mint(monkeypatch)

    session = await create_realtime_transcription_session(
        language="   ", purpose="recording", user=None,
    )

    assert session.language == "multi"
