"""Tests for the active realtime transcription runtime."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.realtime_transcription import (
    RealtimeTranscriptionSession,
    _build_openai_realtime_session,
    create_realtime_transcription_session,
)

OPENAI_REALTIME_MODEL = "gpt-realtime-whisper"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_openai_recording_defaults():
    with patch(
        "app.core.realtime_transcription.create_realtime_client_secret",
        new=AsyncMock(return_value="ek_openai"),
    ):
        session = await create_realtime_transcription_session(language="multi", channels=1)

    assert session == RealtimeTranscriptionSession(
        provider="openai",
        token="ek_openai",
        expires_in_seconds=900,
        sample_rate=24_000,
        audio_format="pcm_24000",
        language="multi",
        channels=1,
        model=OPENAI_REALTIME_MODEL,
        keep_alive_interval_seconds=None,
        commit_strategy="manual",
        no_verbatim=False,
        websocket_url=f"wss://api.openai.com/v1/realtime?model={OPENAI_REALTIME_MODEL}",
        auth_scheme="bearer",
    )


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_ignores_user_recording_choice():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "soniox",
            "recording_live_stt_model": "stt-rt-v4",
        },
    )()

    with patch(
        "app.core.realtime_transcription.create_realtime_client_secret",
        new=AsyncMock(return_value="ek_openai"),
    ):
        session = await create_realtime_transcription_session(
            language="ru",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "openai"
    assert session.model == OPENAI_REALTIME_MODEL
    assert session.language == "ru"
    assert session.channels == 1
    assert session.token == "ek_openai"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_create_dictation_session_ignores_removed_realtime_user_model():
    user = type(
        "User",
        (),
        {
            "dictation_live_stt_provider": "legacy-live",
            "dictation_live_stt_model": "legacy-model",
        },
    )()

    with patch(
        "app.core.realtime_transcription.create_realtime_client_secret",
        new=AsyncMock(return_value="ek_openai"),
    ):
        session = await create_realtime_transcription_session(
            language="en",
            channels=1,
            purpose="dictation",
            user=user,
        )

    assert session.provider == "openai"
    assert session.model == OPENAI_REALTIME_MODEL


@pytest.mark.asyncio
async def test_create_dictation_session_normalizes_language_and_channels():
    with patch(
        "app.core.realtime_transcription.create_realtime_client_secret",
        new=AsyncMock(return_value="ek_openai"),
    ):
        session = await create_realtime_transcription_session(
            language=" RU ",
            channels=0,
            purpose="dictation",
        )

    assert session.provider == "openai"
    assert session.language == "ru"
    assert session.channels == 1


@pytest.mark.asyncio
async def test_create_recording_session_ignores_elevenlabs_user_choice():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "elevenlabs",
            "recording_live_stt_model": "scribe_v2_realtime",
        },
    )()

    with patch(
        "app.core.realtime_transcription.create_realtime_client_secret",
        new=AsyncMock(return_value="ek_openai"),
    ):
        session = await create_realtime_transcription_session(
            language="EN",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "openai"
    assert session.language == "en"
    assert session.channels == 1
    assert session.no_verbatim is False
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_build_openai_realtime_session_requires_api_key():
    with patch(
        "app.core.realtime_transcription.create_realtime_client_secret",
        new=AsyncMock(side_effect=ValueError("OPENAI_API_KEY not configured")),
    ):
        with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
            await _build_openai_realtime_session("ru", 1, model=OPENAI_REALTIME_MODEL)


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_rejects_non_openai_runtime():
    with patch(
        "app.core.realtime_transcription.validate_option",
        return_value=("soniox", "stt-rt-v4"),
    ):
        with pytest.raises(ValueError, match="Unsupported recording_live_stt_provider: soniox"):
            await create_realtime_transcription_session(language="multi")


def test_realtime_transcription_router_exposes_only_session_mint_endpoint():
    """Live STT is a single backend-minted OpenAI path, not provider proxy routing."""
    from app.api.routes.realtime_transcription import router

    route_paths = {getattr(route, "path", None) for route in router.routes}

    assert route_paths == {"/transcription/session"}
