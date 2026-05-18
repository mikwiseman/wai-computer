"""Soniox async batch transcription client (stt-async-v4).

This module is **batch-only**. Realtime Soniox traffic continues to flow
through the existing Inworld gateway (see :mod:`app.core.inworld`); we add a
direct client here for the async file endpoint because Inworld does not proxy
Soniox over the synchronous REST path.

Flow per call (matches the v4 async API):

1. ``POST /v1/files`` — upload binary audio; returns ``{"id": file_id}``.
2. ``POST /v1/transcriptions`` — create job referencing the file with
   ``model="stt-async-v4"`` and ``enable_speaker_diarization=True``.
3. ``GET /v1/transcriptions/{id}`` — poll until ``status="completed"`` or
   ``"error"`` (exponential backoff capped at 8 s, hard 30-minute ceiling).
4. ``GET /v1/transcriptions/{id}/transcript`` — fetch the token list and group
   consecutive tokens by speaker into :class:`TranscriptResult` segments.

On any non-2xx response, job-state ``"error"``, or missing transcript payload
the client raises :class:`RuntimeError` — never returns an empty list. That
keeps the caller informed when something failed instead of silently producing
an empty transcript.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings
from app.core.transcript_utils import TranscriptResult

SONIOX_API_BASE = "https://api.soniox.com"
SONIOX_POLL_INITIAL_DELAY_SECONDS = 1.0
SONIOX_POLL_MAX_DELAY_SECONDS = 8.0
SONIOX_POLL_HARD_TIMEOUT_SECONDS = 30 * 60


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.soniox_api_key:
        raise ValueError("SONIOX_API_KEY not configured")
    return settings.soniox_api_key


def _language_hints(language: str) -> list[str]:
    cleaned = (language or "").strip().lower()
    if not cleaned or cleaned in {"auto", "multi"}:
        return []
    return [cleaned]


def _build_segments_from_tokens(tokens: list[dict[str, Any]]) -> list[TranscriptResult]:
    """Group consecutive Soniox tokens by speaker into segment rows."""
    segments: list[TranscriptResult] = []
    current_speaker: str | None = None
    current_words: list[str] = []
    current_start_ms: int | None = None
    current_end_ms = 0
    current_confidences: list[float] = []

    for token in tokens:
        if not isinstance(token, dict):
            raise RuntimeError("Soniox token entry is not an object")
        text = token.get("text")
        if not isinstance(text, str) or not text:
            continue
        # Skip translation-only tokens — they lack timestamps and would
        # distort segment boundaries if mixed with original-speech tokens.
        if token.get("translation_status") == "translation":
            continue
        speaker_value = token.get("speaker")
        speaker = f"Speaker {speaker_value}" if speaker_value is not None else None
        confidence = float(token.get("confidence", 0.0) or 0.0)
        start_ms = int(token.get("start_ms", 0) or 0)
        end_ms = int(token.get("end_ms", start_ms) or start_ms)

        if current_words and speaker != current_speaker:
            segments.append(
                TranscriptResult(
                    text="".join(current_words).strip(),
                    speaker=current_speaker,
                    is_final=True,
                    start_ms=current_start_ms or 0,
                    end_ms=current_end_ms,
                    confidence=(
                        sum(current_confidences) / len(current_confidences)
                        if current_confidences
                        else 0.0
                    ),
                )
            )
            current_words = []
            current_confidences = []
            current_start_ms = None
        if current_start_ms is None:
            current_speaker = speaker
            current_start_ms = start_ms
        current_words.append(text)
        current_end_ms = end_ms
        current_confidences.append(confidence)

    if current_words:
        segments.append(
            TranscriptResult(
                text="".join(current_words).strip(),
                speaker=current_speaker,
                is_final=True,
                start_ms=current_start_ms or 0,
                end_ms=current_end_ms,
                confidence=(
                    sum(current_confidences) / len(current_confidences)
                    if current_confidences
                    else 0.0
                ),
            )
        )

    return segments


async def _upload_file(
    client: httpx.AsyncClient, audio_data: bytes, content_type: str
) -> str:
    response = await client.post(
        "/v1/files",
        files={"file": ("recording", audio_data, content_type)},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Soniox /v1/files failed status={response.status_code} body={response.text[:512]}"
        )
    body = response.json()
    file_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(file_id, str) or not file_id:
        raise RuntimeError("Soniox /v1/files response missing 'id'")
    return file_id


async def _create_job(
    client: httpx.AsyncClient,
    *,
    file_id: str,
    model: str,
    language: str,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "file_id": file_id,
        "enable_speaker_diarization": True,
        "enable_language_identification": True,
    }
    hints = _language_hints(language)
    if hints:
        payload["language_hints"] = hints

    response = await client.post("/v1/transcriptions", json=payload)
    if response.status_code >= 400:
        raise RuntimeError(
            "Soniox /v1/transcriptions failed "
            f"status={response.status_code} body={response.text[:512]}"
        )
    body = response.json()
    job_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("Soniox /v1/transcriptions response missing 'id'")
    return job_id


async def _wait_for_completion(client: httpx.AsyncClient, job_id: str) -> None:
    delay = SONIOX_POLL_INITIAL_DELAY_SECONDS
    elapsed = 0.0
    while True:
        response = await client.get(f"/v1/transcriptions/{job_id}")
        if response.status_code >= 400:
            raise RuntimeError(
                "Soniox transcription poll failed "
                f"status={response.status_code} body={response.text[:512]}"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Soniox transcription poll returned non-object body")
        status = body.get("status")
        if status == "completed":
            return
        if status == "error":
            error_message = body.get("error_message") or body.get("error") or "unknown"
            raise RuntimeError(f"Soniox transcription job errored: {error_message}")
        # Any other status ("queued", "processing", ...) — keep polling.
        if elapsed >= SONIOX_POLL_HARD_TIMEOUT_SECONDS:
            raise RuntimeError(
                f"Soniox transcription job {job_id} did not finish within "
                f"{SONIOX_POLL_HARD_TIMEOUT_SECONDS}s"
            )
        await asyncio.sleep(delay)
        elapsed += delay
        delay = min(delay * 2, SONIOX_POLL_MAX_DELAY_SECONDS)


async def _fetch_transcript(
    client: httpx.AsyncClient, job_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"/v1/transcriptions/{job_id}/transcript")
    if response.status_code >= 400:
        raise RuntimeError(
            "Soniox transcript fetch failed "
            f"status={response.status_code} body={response.text[:512]}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Soniox transcript response is not an object")
    tokens = body.get("tokens")
    if not isinstance(tokens, list):
        raise RuntimeError("Soniox transcript response missing 'tokens' array")
    return tokens


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    model: str,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
) -> list[TranscriptResult]:
    """Transcribe an audio file through Soniox's async REST API.

    ``channels`` is accepted for signature parity with the other providers but
    Soniox derives the channel layout from the uploaded audio itself.
    """
    del channels  # parameter parity with other transcribe_audio_file fns
    api_key = _require_api_key()

    async with httpx.AsyncClient(
        base_url=SONIOX_API_BASE,
        timeout=300.0,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        file_id = await _upload_file(client, audio_data, content_type)
        job_id = await _create_job(
            client,
            file_id=file_id,
            model=model,
            language=language,
        )
        await _wait_for_completion(client, job_id)
        tokens = await _fetch_transcript(client, job_id)

    return _build_segments_from_tokens(tokens)
