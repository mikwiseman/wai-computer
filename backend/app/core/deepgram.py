"""Deepgram speech-to-text client.

We use different Deepgram models for different jobs:

- :func:`transcribe_audio_file` — POST to ``/v1/listen`` for batch.
- :func:`realtime_websocket_url` — build provider WebSocket URLs for either
  temporary-token direct clients or the backend realtime proxy.

Native realtime clients never receive the long-lived ``DEEPGRAM_API_KEY``.
If the Deepgram key supports ``/v1/auth/grant`` we can mint a direct temporary
token; otherwise the backend proxy uses the server-side key and relays audio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.transcript_utils import TranscriptResult

DEEPGRAM_API_BASE = "https://api.deepgram.com"
DEEPGRAM_NOVA_REALTIME_WS_BASE = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_FLUX_REALTIME_WS_BASE = "wss://api.deepgram.com/v2/listen"
DEEPGRAM_REALTIME_TOKEN_TTL_SECONDS = 30
DEEPGRAM_REALTIME_SAMPLE_RATE = 16_000


def _require_api_key() -> str:
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY not configured")
    return settings.deepgram_api_key


def _normalize_language(language: str) -> str:
    cleaned = (language or "").strip().lower()
    if not cleaned or cleaned == "auto":
        return "multi"
    return cleaned


@dataclass(frozen=True)
class DeepgramRealtimeSession:
    """Connection blob handed to the native client for Deepgram streaming."""

    access_token: str
    websocket_url: str
    model: str
    language: str
    sample_rate: int
    channels: int
    expires_in_seconds: int
    keep_alive_interval_seconds: int | None


async def _create_realtime_access_token() -> tuple[str, int]:
    api_key = _require_api_key()
    async with httpx.AsyncClient(base_url=DEEPGRAM_API_BASE, timeout=15.0) as client:
        response = await client.post(
            "/v1/auth/grant",
            headers={"Authorization": f"Token {api_key}"},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                "Deepgram /v1/auth/grant failed "
                f"status={response.status_code} body={response.text[:512]}"
            )
        body = response.json()

    access_token = body.get("access_token") if isinstance(body, dict) else None
    expires_in = body.get("expires_in") if isinstance(body, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Deepgram auth grant response missing 'access_token'")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise RuntimeError("Deepgram auth grant response missing positive 'expires_in'")
    return access_token, expires_in


def _deepgram_language_hints(language: str) -> list[str]:
    resolved = _normalize_language(language)
    if resolved in {"auto", "multi"}:
        return []
    return [resolved]


def realtime_websocket_url(
    *,
    model: str,
    language: str,
    channels: int = 1,
) -> tuple[str, str, int | None]:
    """Build the Deepgram realtime URL and normalized language metadata."""
    resolved_language = _normalize_language(language)
    resolved_channels = max(1, channels)

    if model.startswith("flux-"):
        params: list[tuple[str, str]] = [
            ("model", model),
            ("encoding", "linear16"),
            ("sample_rate", str(DEEPGRAM_REALTIME_SAMPLE_RATE)),
        ]
        for hint in _deepgram_language_hints(language):
            params.append(("language_hint", hint))
        return (
            f"{DEEPGRAM_FLUX_REALTIME_WS_BASE}?{urlencode(params)}",
            resolved_language,
            None,
        )

    params = [
        ("model", model),
        ("encoding", "linear16"),
        ("sample_rate", str(DEEPGRAM_REALTIME_SAMPLE_RATE)),
        ("channels", str(resolved_channels)),
        ("interim_results", "true"),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("diarize", "true"),
        ("language", resolved_language),
    ]
    return (
        f"{DEEPGRAM_NOVA_REALTIME_WS_BASE}?{urlencode(params)}",
        resolved_language,
        8,
    )


async def mint_realtime_session(
    *,
    model: str,
    language: str,
    channels: int = 1,
) -> DeepgramRealtimeSession:
    """Build the connection blob for a Deepgram streaming session.

    The native client speaks WebSocket directly to ``api.deepgram.com`` and
    authenticates with the short-lived grant token using ``Authorization:
    Bearer``.
    """
    access_token, expires_in_seconds = await _create_realtime_access_token()
    resolved_channels = max(1, channels)
    websocket_url, resolved_language, keep_alive_interval_seconds = realtime_websocket_url(
        model=model,
        language=language,
        channels=resolved_channels,
    )

    return DeepgramRealtimeSession(
        access_token=access_token,
        websocket_url=websocket_url,
        model=model,
        language=resolved_language,
        sample_rate=DEEPGRAM_REALTIME_SAMPLE_RATE,
        channels=resolved_channels,
        expires_in_seconds=expires_in_seconds,
        keep_alive_interval_seconds=keep_alive_interval_seconds,
    )


def _build_segments_from_words(words: list[dict[str, Any]]) -> list[TranscriptResult]:
    """Group consecutive words by speaker into speaker-labeled segments."""
    segments: list[TranscriptResult] = []
    current_speaker: str | None = None
    current_words: list[str] = []
    current_start_ms = 0
    current_end_ms = 0
    current_confidences: list[float] = []

    for word in words:
        if not isinstance(word, dict):
            raise RuntimeError("Deepgram word entry is not an object")
        text = word.get("punctuated_word") or word.get("word")
        if not isinstance(text, str) or not text.strip():
            continue
        speaker_value = word.get("speaker")
        speaker = f"Speaker {speaker_value}" if speaker_value is not None else None
        start_seconds = float(word.get("start", 0.0) or 0.0)
        end_seconds = float(word.get("end", start_seconds) or start_seconds)
        confidence = float(word.get("confidence", 0.0) or 0.0)
        if current_words and speaker != current_speaker:
            segments.append(
                TranscriptResult(
                    text=" ".join(current_words),
                    speaker=current_speaker,
                    is_final=True,
                    start_ms=current_start_ms,
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
        if not current_words:
            current_speaker = speaker
            current_start_ms = int(start_seconds * 1000)
        current_words.append(text)
        current_end_ms = int(end_seconds * 1000)
        current_confidences.append(confidence)

    if current_words:
        segments.append(
            TranscriptResult(
                text=" ".join(current_words),
                speaker=current_speaker,
                is_final=True,
                start_ms=current_start_ms,
                end_ms=current_end_ms,
                confidence=(
                    sum(current_confidences) / len(current_confidences)
                    if current_confidences
                    else 0.0
                ),
            )
        )

    return segments


async def transcribe_audio_file(
    audio_data: bytes,
    *,
    model: str,
    language: str = "en",
    content_type: str = "audio/wav",
    channels: int | None = None,
) -> list[TranscriptResult]:
    """Transcribe an audio file with Deepgram's prerecorded ``/v1/listen`` API."""
    api_key = _require_api_key()
    resolved_language = _normalize_language(language)

    params = {
        "model": model,
        "smart_format": "true",
        "punctuate": "true",
        "diarize": "true",
        "language": resolved_language,
    }
    if channels and channels > 1:
        params["multichannel"] = "true"

    async with httpx.AsyncClient(base_url=DEEPGRAM_API_BASE, timeout=300.0) as client:
        response = await client.post(
            "/v1/listen",
            params=params,
            content=audio_data,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": content_type,
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                "Deepgram /v1/listen failed "
                f"status={response.status_code} body={response.text[:512]}"
            )
        payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError("Deepgram returned a non-object response body")
    results = payload.get("results")
    if not isinstance(results, dict):
        raise RuntimeError("Deepgram response missing 'results' object")
    channels_payload = results.get("channels")
    if not isinstance(channels_payload, list) or not channels_payload:
        raise RuntimeError("Deepgram response missing 'results.channels' array")

    transcripts: list[TranscriptResult] = []
    for channel in channels_payload:
        if not isinstance(channel, dict):
            raise RuntimeError("Deepgram channel entry is not an object")
        alternatives = channel.get("alternatives")
        if not isinstance(alternatives, list) or not alternatives:
            raise RuntimeError("Deepgram channel missing 'alternatives' array")
        top = alternatives[0]
        if not isinstance(top, dict):
            raise RuntimeError("Deepgram alternative entry is not an object")
        words = top.get("words")
        if isinstance(words, list) and words:
            transcripts.extend(_build_segments_from_words(words))
            continue
        text = str(top.get("transcript", "")).strip()
        if not text:
            raise RuntimeError("Deepgram alternative has neither words nor transcript text")
        transcripts.append(
            TranscriptResult(
                text=text,
                speaker=None,
                is_final=True,
                start_ms=0,
                end_ms=0,
                confidence=float(top.get("confidence", 0.0) or 0.0),
            )
        )

    return transcripts
