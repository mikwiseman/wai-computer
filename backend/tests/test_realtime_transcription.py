"""Tests for the active realtime transcription runtime."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.realtime_transcription import (
    RealtimeTranscriptionSession,
    _build_inworld_realtime_session,
    create_realtime_transcription_session,
)


def _fake_inworld_jwt(token: str = "iw-jwt", expires_in_seconds: int = 850):
    return type(
        "InworldJwt",
        (),
        {"token": token, "expires_in_seconds": expires_in_seconds},
    )()


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_inworld_recording_defaults():
    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=_fake_inworld_jwt()),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""

        session = await create_realtime_transcription_session(language="multi", channels=1)

    assert session == RealtimeTranscriptionSession(
        provider="inworld",
        token="iw-jwt",
        expires_in_seconds=850,
        sample_rate=16_000,
        audio_format="linear16_16000",
        language="multi",
        channels=1,
        model="inworld/inworld-stt-1",
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url="wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
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

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=_fake_inworld_jwt()),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""

        session = await create_realtime_transcription_session(
            language="ru",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "inworld"
    assert session.model == "inworld/inworld-stt-1"
    assert session.language == "ru"
    assert session.channels == 2
    assert session.token == "iw-jwt"
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_create_dictation_session_ignores_removed_openai_realtime_model():
    user = type(
        "User",
        (),
        {
            "dictation_live_stt_provider": "openai",
            "dictation_live_stt_model": "gpt-realtime-whisper",
        },
    )()

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=_fake_inworld_jwt()),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""

        session = await create_realtime_transcription_session(
            language="en",
            channels=1,
            purpose="dictation",
            user=user,
        )

    assert session.provider == "inworld"
    assert session.model == "inworld/inworld-stt-1"


@pytest.mark.asyncio
async def test_create_dictation_session_normalizes_language_and_channels():
    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=_fake_inworld_jwt()),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""

        session = await create_realtime_transcription_session(
            language=" RU ",
            channels=0,
            purpose="dictation",
        )

    assert session.provider == "inworld"
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

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=_fake_inworld_jwt()),
        ),
    ):
        mock_settings.return_value.inworld_api_key = "user:pass"
        mock_settings.return_value.inworld_workspace = ""

        session = await create_realtime_transcription_session(
            language="EN",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "inworld"
    assert session.language == "en"
    assert session.channels == 2
    assert session.no_verbatim is False
    assert session.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_build_inworld_realtime_session_requires_api_key():
    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.inworld_api_key = ""

        with pytest.raises(ValueError, match="INWORLD_API_KEY not configured"):
            await _build_inworld_realtime_session("ru", 1, model="inworld/inworld-stt-1")


def test_realtime_transcription_router_exposes_only_session_mint_endpoint():
    """Live STT is a single backend-minted Inworld path, not provider proxy routing."""
    from app.api.routes.realtime_transcription import router

    route_paths = {getattr(route, "path", None) for route in router.routes}

    assert route_paths == {"/transcription/session"}
