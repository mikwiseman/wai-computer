"""Tests for the Deepgram batch + realtime client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.deepgram import (
    DEEPGRAM_REALTIME_SAMPLE_RATE,
    mint_realtime_session,
    transcribe_audio_file,
)


def _mock_response(status_code: int, body: Any) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json = MagicMock(return_value=body)
    response.text = json.dumps(body) if not isinstance(body, str) else body
    return response


def _patch_client_post(response: MagicMock):
    """Patch httpx.AsyncClient context manager so client.post returns ``response``."""
    client_mock = MagicMock()
    client_mock.post = AsyncMock(return_value=response)
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    return patch("app.core.deepgram.httpx.AsyncClient", return_value=async_ctx)


def _word(
    text: str,
    start: float,
    end: float,
    confidence: float,
    speaker: int,
) -> dict[str, Any]:
    return {
        "punctuated_word": text,
        "start": start,
        "end": end,
        "confidence": confidence,
        "speaker": speaker,
    }


@pytest.mark.asyncio
async def test_transcribe_audio_file_returns_speaker_segments():
    body = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Hello world how are you",
                            "confidence": 0.96,
                            "words": [
                                _word("Hello", 0.0, 0.4, 0.95, 0),
                                _word("world.", 0.4, 0.8, 0.96, 0),
                                _word("How", 1.0, 1.2, 0.92, 1),
                                _word("are", 1.2, 1.3, 0.93, 1),
                                _word("you?", 1.3, 1.6, 0.94, 1),
                            ],
                        }
                    ]
                }
            ]
        }
    }
    response = _mock_response(200, body)

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response),
    ):
        mock_settings.return_value.deepgram_api_key = "test-key"
        results = await transcribe_audio_file(
            b"audio",
            model="nova-3",
            language="en",
            content_type="audio/wav",
        )

    assert len(results) == 2
    assert results[0].speaker == "Speaker 0"
    assert results[0].text == "Hello world."
    assert results[0].start_ms == 0
    assert results[0].end_ms == 800
    assert results[1].speaker == "Speaker 1"
    assert results[1].text == "How are you?"
    assert results[1].start_ms == 1000
    assert results[1].end_ms == 1600


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_on_non_2xx():
    response = _mock_response(401, {"error": "unauthorized"})
    response.text = '{"error":"unauthorized"}'

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response),
    ):
        mock_settings.return_value.deepgram_api_key = "test-key"
        with pytest.raises(RuntimeError, match="Deepgram /v1/listen failed status=401"):
            await transcribe_audio_file(
                b"audio",
                model="nova-3",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_on_missing_results():
    response = _mock_response(200, {"metadata": {}})

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response),
    ):
        mock_settings.return_value.deepgram_api_key = "test-key"
        with pytest.raises(RuntimeError, match="Deepgram response missing 'results' object"):
            await transcribe_audio_file(
                b"audio",
                model="nova-3",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_on_missing_channels():
    response = _mock_response(200, {"results": {}})

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response),
    ):
        mock_settings.return_value.deepgram_api_key = "test-key"
        with pytest.raises(RuntimeError, match="results.channels"):
            await transcribe_audio_file(
                b"audio",
                model="nova-3",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_falls_back_to_top_level_transcript():
    body = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Single transcript without words array",
                            "confidence": 0.91,
                            "words": [],
                        }
                    ]
                }
            ]
        }
    }
    response = _mock_response(200, body)

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response),
    ):
        mock_settings.return_value.deepgram_api_key = "test-key"
        results = await transcribe_audio_file(
            b"audio",
            model="nova-3",
            language="en",
            content_type="audio/wav",
        )

    assert len(results) == 1
    assert results[0].text == "Single transcript without words array"
    assert results[0].speaker is None


def test_mint_realtime_session_builds_websocket_url_with_required_params():
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = "test-key"
        session = mint_realtime_session(model="nova-3", language="multi", channels=2)

    assert session.api_key == "test-key"
    assert session.model == "nova-3"
    assert session.language == "multi"
    assert session.channels == 2
    assert session.sample_rate == DEEPGRAM_REALTIME_SAMPLE_RATE
    assert "wss://api.deepgram.com/v1/listen?" in session.websocket_url
    assert "model=nova-3" in session.websocket_url
    assert "encoding=linear16" in session.websocket_url
    assert "diarize=true" in session.websocket_url
    assert "smart_format=true" in session.websocket_url
    assert "language=multi" in session.websocket_url


def test_mint_realtime_session_requires_api_key():
    with patch("app.core.deepgram.get_settings") as mock_settings:
        mock_settings.return_value.deepgram_api_key = ""
        with pytest.raises(ValueError, match="DEEPGRAM_API_KEY not configured"):
            mint_realtime_session(model="nova-3", language="en", channels=1)
