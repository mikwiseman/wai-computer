"""Regression tests for the no-silent-fallback rule (AGENTS.md lines 5-25).

These tests pin the contract that provider clients RAISE on
malformed upstream payloads rather than returning an empty list. Previously
each client silently returned ``[]``, hiding the failure from callers.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.elevenlabs import transcribe_audio_file as elevenlabs_transcribe_audio_file


def _mock_response(status_code: int, body: Any) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json = MagicMock(return_value=body)
    response.text = json.dumps(body) if not isinstance(body, str) else body
    response.raise_for_status = MagicMock()
    return response


def _patch_client_post(
    response: MagicMock, module_path: str
):
    client_mock = MagicMock()
    client_mock.post = AsyncMock(return_value=response)
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    return patch(f"{module_path}.httpx.AsyncClient", return_value=async_ctx)


@pytest.mark.asyncio
async def test_elevenlabs_transcribe_raises_on_unexpected_payload_type():
    """A non-dict response payload must raise rather than silently return []."""
    # Provider returns a JSON array at the top level (neither dict nor list of transcripts).
    response = _mock_response(200, "raw string response")
    response.json = MagicMock(return_value="raw string response")

    with (
        patch("app.core.elevenlabs.get_settings") as mock_settings,
        _patch_client_post(response, "app.core.elevenlabs"),
    ):
        mock_settings.return_value.elevenlabs_api_key = "test-key"
        mock_settings.return_value.elevenlabs_speech_to_text_model = "scribe_v2"
        mock_settings.return_value.elevenlabs_no_verbatim = True
        with pytest.raises(RuntimeError, match="unexpected payload type"):
            await elevenlabs_transcribe_audio_file(
                b"audio",
                model="scribe_v2",
                language="en",
                content_type="audio/raw",
            )
