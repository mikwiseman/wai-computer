"""OpenAI speech-to-text helpers."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.core.transcript_utils import TranscriptResult

OPENAI_API_BASE = "https://api.openai.com"
OPENAI_REALTIME_WS_URL = "wss://api.openai.com/v1/realtime"
OPENAI_REALTIME_SAMPLE_RATE = 24_000
OPENAI_REALTIME_TOKEN_TTL_SECONDS = 15 * 60


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")
    return settings.openai_api_key


def build_realtime_transcription_session_update(
    *,
    model: str,
    language: str,
    turn_detection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the OpenAI realtime transcription session update payload."""
    transcription: dict[str, Any] = {"model": model}
    if language and language != "multi":
        transcription["language"] = language

    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": OPENAI_REALTIME_SAMPLE_RATE,
                    },
                    "transcription": transcription,
                    "turn_detection": turn_detection,
                }
            },
        },
    }


async def create_realtime_client_secret(*, model: str, language: str) -> str:
    """Create an ephemeral client secret for OpenAI Realtime transcription."""
    api_key = _require_api_key()
    session_update = build_realtime_transcription_session_update(
        model=model,
        language=language,
        turn_detection=None,
    )
    payload = {"session": session_update["session"]}

    async with httpx.AsyncClient(base_url=OPENAI_API_BASE, timeout=15.0) as client:
        response = await client.post(
            "/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    value = None
    if isinstance(body, dict):
        client_secret = body.get("client_secret")
        if isinstance(client_secret, dict):
            value = client_secret.get("value")
        if value is None:
            value = body.get("value") or body.get("secret")

    if not isinstance(value, str) or not value:
        raise RuntimeError("OpenAI returned an invalid realtime client secret")
    return value


def realtime_websocket_url(model: str) -> str:
    return f"{OPENAI_REALTIME_WS_URL}?model={model}"


def _result_from_openai_segment(segment: dict[str, Any]) -> TranscriptResult | None:
    text = str(segment.get("text", "")).strip()
    if not text:
        return None
    start = segment.get("start", 0)
    end = segment.get("end", start)
    return TranscriptResult(
        text=text,
        speaker=None,
        is_final=True,
        start_ms=int(float(start or 0) * 1000),
        end_ms=int(float(end or 0) * 1000),
        confidence=0.0,
    )


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    model: str,
    language: str = "en",
    content_type: str = "audio/wav",
) -> list[TranscriptResult]:
    """Transcribe an audio file with OpenAI's Audio Transcriptions API."""
    api_key = _require_api_key()
    data: list[tuple[str, str]] = [
        ("model", model),
        ("response_format", "verbose_json"),
    ]
    if language and language != "multi":
        data.append(("language", language))

    files = {"file": ("recording", audio_data, content_type)}

    async with httpx.AsyncClient(base_url=OPENAI_API_BASE, timeout=300.0) as client:
        response = await client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files=files,
        )
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI returned an invalid transcription payload")

    segments = payload.get("segments")
    if isinstance(segments, list):
        results = [
            result
            for segment in segments
            if isinstance(segment, dict)
            for result in [_result_from_openai_segment(segment)]
            if result is not None
        ]
        if results:
            return results

    text = str(payload.get("text", "")).strip()
    if not text:
        raise RuntimeError("OpenAI transcribe returned empty text and no segments")
    return [
        TranscriptResult(
            text=text,
            speaker=None,
            is_final=True,
            start_ms=0,
            end_ms=0,
            confidence=0.0,
        )
    ]
