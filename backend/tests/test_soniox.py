"""Tests for the Soniox direct async batch client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.soniox import transcribe_audio_file


def _resp(status_code: int, body: Any) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json = MagicMock(return_value=body)
    response.text = json.dumps(body) if not isinstance(body, str) else body
    return response


def _patch_async_client(post_responses: list[MagicMock], get_responses: list[MagicMock]):
    """Patch httpx.AsyncClient so .post returns ``post_responses`` in order,
    and .get returns ``get_responses`` in order."""
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=post_responses)
    client_mock.get = AsyncMock(side_effect=get_responses)
    async_ctx = MagicMock()
    async_ctx.__aenter__ = AsyncMock(return_value=client_mock)
    async_ctx.__aexit__ = AsyncMock(return_value=None)
    return patch("app.core.soniox.httpx.AsyncClient", return_value=async_ctx), client_mock


def _token(
    text: str,
    start_ms: int,
    end_ms: int,
    confidence: float,
    speaker: int,
) -> dict[str, Any]:
    return {
        "text": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "confidence": confidence,
        "speaker": speaker,
    }


@pytest.mark.asyncio
async def test_transcribe_audio_file_three_step_flow_returns_speaker_segments():
    upload_resp = _resp(200, {"id": "file_abc"})
    create_resp = _resp(200, {"id": "tx_xyz", "status": "processing"})
    poll_resp = _resp(200, {"status": "completed"})
    transcript_resp = _resp(
        200,
        {
            "tokens": [
                _token("Hello", 0, 400, 0.97, 1),
                _token(" world", 400, 800, 0.95, 1),
                _token(" How", 1000, 1200, 0.94, 2),
                _token(" are", 1200, 1300, 0.93, 2),
                _token(" you?", 1300, 1600, 0.96, 2),
            ]
        },
    )

    patcher, client_mock = _patch_async_client(
        [upload_resp, create_resp],
        [poll_resp, transcript_resp],
    )

    with (
        patch("app.core.soniox.get_settings") as mock_settings,
        patch("app.core.soniox.asyncio.sleep", new=AsyncMock()),
        patcher,
    ):
        mock_settings.return_value.soniox_api_key = "test-key"
        results = await transcribe_audio_file(
            b"audio",
            model="stt-async-v4",
            language="en",
            content_type="audio/wav",
        )

    assert len(results) == 2
    assert results[0].speaker == "Speaker 1"
    assert results[0].text == "Hello world"
    assert results[0].start_ms == 0
    assert results[0].end_ms == 800
    assert results[1].speaker == "Speaker 2"
    assert results[1].text == "How are you?"
    assert results[1].start_ms == 1000
    assert results[1].end_ms == 1600

    # Verify create-job call shape.
    create_call = client_mock.post.await_args_list[1]
    assert create_call.args == ("/v1/transcriptions",)
    job_payload = create_call.kwargs["json"]
    assert job_payload["model"] == "stt-async-v4"
    assert job_payload["file_id"] == "file_abc"
    assert job_payload["enable_speaker_diarization"] is True
    assert job_payload["language_hints"] == ["en"]


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_on_job_error():
    upload_resp = _resp(200, {"id": "file_abc"})
    create_resp = _resp(200, {"id": "tx_xyz"})
    poll_resp = _resp(200, {"status": "error", "error_message": "audio decode failed"})

    patcher, _ = _patch_async_client([upload_resp, create_resp], [poll_resp])

    with (
        patch("app.core.soniox.get_settings") as mock_settings,
        patch("app.core.soniox.asyncio.sleep", new=AsyncMock()),
        patcher,
    ):
        mock_settings.return_value.soniox_api_key = "test-key"
        with pytest.raises(RuntimeError, match="audio decode failed"):
            await transcribe_audio_file(
                b"audio",
                model="stt-async-v4",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_on_upload_failure():
    upload_resp = _resp(403, {"error": "forbidden"})
    upload_resp.text = '{"error":"forbidden"}'

    patcher, _ = _patch_async_client([upload_resp], [])

    with (
        patch("app.core.soniox.get_settings") as mock_settings,
        patcher,
    ):
        mock_settings.return_value.soniox_api_key = "test-key"
        with pytest.raises(RuntimeError, match="Soniox /v1/files failed status=403"):
            await transcribe_audio_file(
                b"audio",
                model="stt-async-v4",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_raises_when_transcript_missing_tokens():
    upload_resp = _resp(200, {"id": "file_abc"})
    create_resp = _resp(200, {"id": "tx_xyz"})
    poll_resp = _resp(200, {"status": "completed"})
    transcript_resp = _resp(200, {"text": "some text but no tokens array"})

    patcher, _ = _patch_async_client(
        [upload_resp, create_resp],
        [poll_resp, transcript_resp],
    )

    with (
        patch("app.core.soniox.get_settings") as mock_settings,
        patch("app.core.soniox.asyncio.sleep", new=AsyncMock()),
        patcher,
    ):
        mock_settings.return_value.soniox_api_key = "test-key"
        with pytest.raises(RuntimeError, match="missing 'tokens'"):
            await transcribe_audio_file(
                b"audio",
                model="stt-async-v4",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_requires_api_key():
    with patch("app.core.soniox.get_settings") as mock_settings:
        mock_settings.return_value.soniox_api_key = ""
        with pytest.raises(ValueError, match="SONIOX_API_KEY not configured"):
            await transcribe_audio_file(
                b"audio",
                model="stt-async-v4",
                language="en",
                content_type="audio/wav",
            )


@pytest.mark.asyncio
async def test_transcribe_audio_file_skips_translation_tokens():
    upload_resp = _resp(200, {"id": "file_abc"})
    create_resp = _resp(200, {"id": "tx_xyz"})
    poll_resp = _resp(200, {"status": "completed"})
    transcript_resp = _resp(
        200,
        {
            "tokens": [
                {"text": "Hola", "start_ms": 0, "end_ms": 400, "confidence": 0.9, "speaker": 1},
                # Translation-only token has no usable timestamps and should be skipped.
                {"text": " Hello", "translation_status": "translation", "speaker": 1},
                {"text": " mundo", "start_ms": 400, "end_ms": 800, "confidence": 0.9, "speaker": 1},
            ]
        },
    )

    patcher, _ = _patch_async_client(
        [upload_resp, create_resp],
        [poll_resp, transcript_resp],
    )

    with (
        patch("app.core.soniox.get_settings") as mock_settings,
        patch("app.core.soniox.asyncio.sleep", new=AsyncMock()),
        patcher,
    ):
        mock_settings.return_value.soniox_api_key = "test-key"
        results = await transcribe_audio_file(
            b"audio",
            model="stt-async-v4",
            language="es",
            content_type="audio/wav",
        )

    assert len(results) == 1
    assert results[0].text == "Hola mundo"
