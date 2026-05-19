"""Tests for realtime transcription provider abstraction."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.realtime_transcription import (
    RealtimeTranscriptionSession,
    _create_elevenlabs_realtime_token,
)


@pytest.mark.asyncio
async def test_create_elevenlabs_realtime_token_uses_token_value():
    response = httpx.Response(
        200,
        json={"token": "sutkn_live_123"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"),
    )

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "xi-key"
        token, expires_in = await _create_elevenlabs_realtime_token()

    assert token == "sutkn_live_123"
    assert expires_in == 900


@pytest.mark.asyncio
async def test_create_elevenlabs_realtime_token_rejects_invalid_payload():
    response = httpx.Response(
        200,
        json={"token": ""},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"),
    )

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "xi-key"
        with pytest.raises(RuntimeError, match="invalid realtime transcription token"):
            await _create_elevenlabs_realtime_token()


@pytest.mark.asyncio
async def test_create_elevenlabs_realtime_token_requires_api_key():
    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.elevenlabs_api_key = ""
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY not configured"):
            await _create_elevenlabs_realtime_token()


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_elevenlabs_defaults():
    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription._create_elevenlabs_realtime_token",
            new=AsyncMock(return_value=("el-token", 900)),
        ),
    ):
        mock_settings.return_value.elevenlabs_realtime_speech_to_text_model = "scribe_v2_realtime"
        mock_settings.return_value.elevenlabs_no_verbatim = True

        from app.core.realtime_transcription import create_realtime_transcription_session

        session = await create_realtime_transcription_session(language="multi", channels=1)

    assert session == RealtimeTranscriptionSession(
        provider="elevenlabs",
        token="el-token",
        expires_in_seconds=900,
        sample_rate=16_000,
        audio_format="pcm_16000",
        language="multi",
        channels=1,
        model="scribe_v2_realtime",
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=True,
    )


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_soniox_recording_choice():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "soniox",
            "recording_live_stt_model": "stt-rt-v4",
        },
    )()
    from app.core.realtime_transcription import create_realtime_transcription_session

    fake_soniox = type(
        "SonioxSession",
        (),
        {
            "temporary_api_key": "sx-temp",
            "expires_in_seconds": 60,
            "sample_rate": 16_000,
            "language": "ru",
            "channels": 2,
            "model": "stt-rt-v4",
            "websocket_url": "wss://stt-rt.soniox.com/transcribe-websocket",
        },
    )()
    with patch(
        "app.core.realtime_transcription.mint_soniox_realtime_session",
        new=AsyncMock(return_value=fake_soniox),
    ):
        session = await create_realtime_transcription_session(
            language="ru",
            channels=2,
            purpose="recording",
            user=user,
        )

    assert session.provider == "soniox"
    assert session.model == "stt-rt-v4"
    assert session.language == "ru"
    assert session.channels == 2
    assert session.token == "sx-temp"
    assert session.auth_scheme == "message_api_key"
    assert session.websocket_url == "wss://stt-rt.soniox.com/transcribe-websocket"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_uses_inworld_bearer_jwt():
    user = type(
        "User",
        (),
        {
            "recording_live_stt_provider": "inworld",
            "recording_live_stt_model": "inworld/inworld-stt-1",
        },
    )()
    fake_jwt = type(
        "InworldJwt",
        (),
        {"token": "iw-jwt", "expires_in_seconds": 850},
    )()

    from app.core.realtime_transcription import create_realtime_transcription_session

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch(
            "app.core.realtime_transcription.mint_inworld_client_jwt",
            new=AsyncMock(return_value=fake_jwt),
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
    assert session.expires_in_seconds == 850
    assert session.websocket_url == "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"


@pytest.mark.asyncio
async def test_create_realtime_transcription_session_rejects_bad_recording_model():
    user = type(
        "User",
        (),
        {"recording_live_stt_provider": "openai", "recording_live_stt_model": "bad-model"},
    )()
    from app.core.realtime_transcription import create_realtime_transcription_session

    with pytest.raises(ValueError, match="Unsupported recording_live_stt option"):
        await create_realtime_transcription_session(user=user)


@pytest.mark.asyncio
async def test_create_dictation_session_rejects_removed_openai_realtime_model():
    user = type(
        "User",
        (),
        {
            "dictation_live_stt_provider": "openai",
            "dictation_live_stt_model": "gpt-realtime-whisper",
        },
    )()
    from app.core.realtime_transcription import create_realtime_transcription_session

    with pytest.raises(ValueError, match="Unsupported dictation_live_stt option"):
        await create_realtime_transcription_session(
            language="en",
            channels=1,
            purpose="dictation",
            user=user,
        )
