"""Inworld AI realtime STT integration.

Inworld exposes a unified WebSocket endpoint that fans out to multiple
underlying STT engines (`inworld/inworld-stt-1`, `soniox/stt-rt-v4`,
`assemblyai/u3-rt-pro`, etc.) selected via the `transcribe_config.model_id`
field of the first WebSocket message. We use `soniox/stt-rt-v4` for
dictation — best-in-class on Russian per Soniox's published multilingual
benchmarks (human-parity across 60+ languages, semantic endpoint detection,
backward-compatible with v3).

Authentication is HTTP Basic over a base64-encoded `<id>:<secret>` pair
held in a single `INWORLD_API_KEY` env var. Per Inworld docs the WebSocket
accepts the same credential as a `?key=Basic+<base64>` query parameter for
clients that cannot inject custom headers — but our Swift client uses
URLSessionWebSocketTask with proper headers, so we mint a session payload
with the credential and let the client construct its own connect.

We do NOT cache the credential client-side; the backend issues short-lived
session payloads on demand. JWT-based mint can be added later if compliance
needs it.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.transcript_utils import TranscriptResult

INWORLD_API_BASE = "https://api.inworld.ai"
INWORLD_STT_WS_URL = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"


@dataclass(frozen=True)
class InworldSttSession:
    """Realtime STT session payload returned by the backend to a Swift client."""

    auth_header: str  # value for `Authorization` header (e.g. "Basic <base64>")
    websocket_url: str
    model_id: str
    language: str
    audio_encoding: str  # always "LINEAR16" for streaming
    sample_rate_hertz: int
    number_of_channels: int


def normalise_inworld_credential(raw: str) -> str:
    """Return a base64 string suitable for the `Authorization: Basic ...` header.

    Accepts either a `id:secret` pair or an already-base64-encoded value.
    Raises ValueError if the input cannot be coerced into a valid Basic
    credential.
    """
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Inworld API key is empty")

    # If the value is already base64, decoding it should yield bytes that
    # contain a colon — that's our heuristic.
    try:
        decoded = base64.b64decode(cleaned, validate=True)
        if b":" in decoded:
            return cleaned
    except (binascii.Error, ValueError):
        pass

    # Otherwise treat as raw `id:secret` and encode it.
    if ":" not in cleaned:
        raise ValueError(
            "Inworld API key must be either base64-encoded or in `id:secret` form"
        )
    return base64.b64encode(cleaned.encode("utf-8")).decode("ascii")


def build_session(
    *,
    api_key: str,
    model_id: str = "soniox/stt-rt-v4",
    language: str = "multi",
    sample_rate: int = 16_000,
    channels: int = 1,
) -> InworldSttSession:
    """Mint an Inworld realtime STT session payload for the Swift client.

    The Swift client uses the auth_header value with URLSessionWebSocketTask
    and sends an initial `transcribe_config` message with the supplied
    parameters.
    """
    base64_key = normalise_inworld_credential(api_key)
    auth_header = f"Basic {base64_key}"

    # Inworld accepts BCP-47 language codes (`en-US`, `ru`) and "multi" for
    # auto-detect. Soniox v4 RT supports the common BCP-47 set.
    resolved_language = language.strip() or "multi"

    return InworldSttSession(
        auth_header=auth_header,
        websocket_url=INWORLD_STT_WS_URL,
        model_id=model_id.strip(),
        language=resolved_language,
        audio_encoding="LINEAR16",
        sample_rate_hertz=sample_rate,
        number_of_channels=max(1, channels),
    )


def inline_query_url(session: InworldSttSession) -> str:
    """Return a websocket URL that includes the credential as a query
    parameter — useful for browsers / WebView clients that cannot send
    custom headers. Native macOS clients should prefer the header form.
    """
    params = {
        "key": session.auth_header,
    }
    return f"{session.websocket_url}?{urlencode(params)}"


def _audio_encoding_for_content_type(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized in {"audio/raw", "application/octet-stream"}:
        return "LINEAR16"
    if normalized in {"audio/mpeg", "audio/mp3", "audio/mpga"}:
        return "MP3"
    if normalized in {"audio/ogg", "audio/opus"}:
        return "OGG_OPUS"
    if normalized == "audio/flac":
        return "FLAC"
    return "AUTO_DETECT"


def _timestamp_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    # Inworld examples use millisecond fields for word timestamps. Some
    # upstream models use seconds; treat small decimal values as seconds.
    if 0 <= numeric < 10_000 and not float(numeric).is_integer():
        numeric *= 1000
    return int(numeric)


def _result_from_transcription(payload: dict[str, Any]) -> TranscriptResult | None:
    text = (
        str(payload.get("transcript") or payload.get("text") or "")
        .strip()
    )
    if not text:
        return None

    words = payload.get("word_timestamps") or payload.get("wordTimestamps") or payload.get("words")
    start_ms = 0
    end_ms = 0
    speaker = None
    if isinstance(words, list) and words:
        typed_words = [word for word in words if isinstance(word, dict)]
        if typed_words:
            first = typed_words[0]
            last = typed_words[-1]
            start_ms = (
                _timestamp_ms(first.get("start_time_ms"))
                or _timestamp_ms(first.get("startMs"))
                or _timestamp_ms(first.get("start_ms"))
                or _timestamp_ms(first.get("start"))
                or 0
            )
            end_ms = (
                _timestamp_ms(last.get("end_time_ms"))
                or _timestamp_ms(last.get("endMs"))
                or _timestamp_ms(last.get("end_ms"))
                or _timestamp_ms(last.get("end"))
                or start_ms
            )
            raw_speaker = first.get("speaker") or first.get("speaker_id")
            speaker = str(raw_speaker) if raw_speaker else None

    return TranscriptResult(
        text=text,
        speaker=speaker,
        is_final=bool(payload.get("is_final", payload.get("isFinal", True))),
        start_ms=start_ms,
        end_ms=end_ms,
        confidence=float(payload.get("confidence") or 0.0),
    )


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    model: str,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
) -> list[TranscriptResult]:
    """Transcribe an audio file with Inworld's synchronous STT API."""
    settings = get_settings()
    if not settings.inworld_api_key:
        raise ValueError("INWORLD_API_KEY not configured")

    config: dict[str, Any] = {
        "model_id": model,
        "audio_encoding": _audio_encoding_for_content_type(content_type),
        "number_of_channels": max(1, channels or 1),
    }
    if language and language != "multi":
        config["language"] = language

    payload = {
        "transcribe_config": config,
        "audio_data": {"content": base64.b64encode(audio_data).decode("ascii")},
    }

    auth_header = f"Basic {normalise_inworld_credential(settings.inworld_api_key)}"
    async with httpx.AsyncClient(base_url=INWORLD_API_BASE, timeout=300.0) as client:
        response = await client.post(
            "/stt/v1/transcribe",
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    if not isinstance(body, dict):
        raise RuntimeError("Inworld returned an invalid transcription payload")

    transcription = body.get("transcription")
    if isinstance(transcription, dict):
        result = _result_from_transcription(transcription)
        return [result] if result else []

    results = body.get("transcriptions")
    if isinstance(results, list):
        return [
            result
            for item in results
            if isinstance(item, dict)
            for result in [_result_from_transcription(item)]
            if result is not None
        ]

    return []
