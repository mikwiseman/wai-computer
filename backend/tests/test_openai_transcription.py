"""Tests for OpenAI realtime speech-to-text helpers."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.openai_transcription import (
    build_realtime_transcription_session_update,
    create_realtime_client_secret,
    realtime_websocket_url,
)


def test_build_realtime_transcription_session_update_uses_24khz_pcm():
    payload = build_realtime_transcription_session_update(
        model="gpt-realtime-whisper",
        language="en",
        turn_detection=None,
    )

    session = payload["session"]
    audio_input = session["audio"]["input"]
    assert session["type"] == "transcription"
    assert audio_input["format"] == {"type": "audio/pcm", "rate": 24_000}
    assert audio_input["transcription"] == {
        "model": "gpt-realtime-whisper",
        "delay": "low",
        "language": "en",
    }
    assert audio_input["turn_detection"] is None


def test_build_realtime_transcription_session_update_omits_multi_language_hint():
    payload = build_realtime_transcription_session_update(
        model="gpt-realtime-whisper",
        language="multi",
        turn_detection=None,
    )

    transcription = payload["session"]["audio"]["input"]["transcription"]
    assert transcription == {"model": "gpt-realtime-whisper", "delay": "low"}


@pytest.mark.asyncio
async def test_create_realtime_client_secret_posts_transcription_session():
    response = httpx.Response(
        200,
        json={"client_secret": {"value": "ek_test"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/realtime/client_secrets"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)) as mock_post,
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        token = await create_realtime_client_secret(
            model="gpt-realtime-whisper",
            language="multi",
        )

    assert token == "ek_test"
    kwargs = mock_post.await_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer sk-test"}
    assert kwargs["json"]["session"]["type"] == "transcription"
    transcription = kwargs["json"]["session"]["audio"]["input"]["transcription"]
    assert transcription == {"model": "gpt-realtime-whisper", "delay": "low"}


@pytest.mark.asyncio
async def test_create_realtime_client_secret_accepts_top_level_value():
    response = httpx.Response(
        200,
        json={"value": "ek_top_level"},
        request=httpx.Request("POST", "https://api.openai.com/v1/realtime/client_secrets"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        token = await create_realtime_client_secret(
            model="gpt-realtime-whisper",
            language="en",
        )

    assert token == "ek_top_level"


@pytest.mark.asyncio
async def test_create_realtime_client_secret_rejects_invalid_secret_response():
    response = httpx.Response(
        200,
        json={"client_secret": {"id": "missing-value"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/realtime/client_secrets"),
    )

    with (
        patch("app.core.openai_transcription.get_settings") as mock_settings,
        patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)),
    ):
        mock_settings.return_value.openai_api_key = "sk-test"
        with pytest.raises(RuntimeError, match="invalid realtime client secret"):
            await create_realtime_client_secret(
                model="gpt-realtime-whisper",
                language="multi",
            )


@pytest.mark.asyncio
async def test_create_realtime_client_secret_requires_openai_api_key():
    with patch("app.core.openai_transcription.get_settings") as mock_settings:
        mock_settings.return_value.openai_api_key = ""
        with pytest.raises(ValueError, match="OPENAI_API_KEY not configured"):
            await create_realtime_client_secret(
                model="gpt-realtime-whisper",
                language="multi",
            )


def test_realtime_websocket_url_uses_transcription_intent():
    assert realtime_websocket_url() == "wss://api.openai.com/v1/realtime?intent=transcription"
