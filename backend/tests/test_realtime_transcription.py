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
        json={"token": "single-use-token-for-test"},
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"),
    )

    with (
        patch("app.core.realtime_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.elevenlabs_api_key = "xi-key"
        token, expires_in = await _create_elevenlabs_realtime_token()

    assert token == "single-use-token-for-test"
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
        mock_settings.return_value.speech_to_text_provider = "elevenlabs"
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
async def test_create_realtime_transcription_session_rejects_non_elevenlabs_provider():
    with patch("app.core.realtime_transcription.get_settings") as mock_settings:
        mock_settings.return_value.speech_to_text_provider = "unsupported-provider"

        from app.core.realtime_transcription import create_realtime_transcription_session

        with pytest.raises(ValueError, match="Only elevenlabs is supported"):
            await create_realtime_transcription_session()
