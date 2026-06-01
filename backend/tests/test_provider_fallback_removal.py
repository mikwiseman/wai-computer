"""Regression tests for the no-silent-fallback rule (AGENTS.md lines 5-25).

These tests pin the contract that the file STT client RAISES on malformed
upstream payloads rather than returning an empty list. Previously providers
silently returned ``[]``, hiding the failure from callers.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.deepgram import transcribe_audio_file as deepgram_transcribe_audio_file


def _mock_response(status_code: int, body: Any) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json = MagicMock(return_value=body)
    response.text = json.dumps(body) if not isinstance(body, str) else body
    response.raise_for_status = MagicMock()
    return response


def _patch_client_post(response: MagicMock, module_path: str):
    client_mock = MagicMock()
    client_mock.post = AsyncMock(return_value=response)
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    return patch(f"{module_path}.httpx.AsyncClient", return_value=async_ctx)


@pytest.mark.asyncio
async def test_deepgram_transcribe_raises_on_unexpected_payload_type():
    """A non-dict response payload must raise rather than silently return []."""
    response = _mock_response(200, "raw string response")
    response.json = MagicMock(return_value="raw string response")

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response, "app.core.deepgram"),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        with pytest.raises(RuntimeError, match="unexpected payload type"):
            await deepgram_transcribe_audio_file(
                b"audio",
                language="en",
                content_type="audio/raw",
            )


@pytest.mark.asyncio
async def test_deepgram_transcribe_raises_on_invalid_utterance_entry():
    """Malformed utterance entries must not collapse into a no-speech result."""
    response = _mock_response(
        200,
        {
            "results": {
                "utterances": [
                    {"transcript": "valid", "start": 0.0, "end": 0.5, "speaker": 0},
                    "bad-entry",
                ]
            }
        },
    )

    with (
        patch("app.core.deepgram.get_settings") as mock_settings,
        _patch_client_post(response, "app.core.deepgram"),
    ):
        mock_settings.return_value.deepgram_api_key = "deepgram-test-key"
        with pytest.raises(RuntimeError, match="invalid utterance entry"):
            await deepgram_transcribe_audio_file(
                b"audio",
                language="en",
                content_type="audio/raw",
            )
