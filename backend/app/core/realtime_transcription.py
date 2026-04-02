"""ElevenLabs-backed realtime speech-to-text sessions."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.core.elevenlabs import ELEVENLABS_API_BASE

ELEVENLABS_TOKEN_TTL_SECONDS = 15 * 60
DEFAULT_SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class RealtimeTranscriptionSession:
    """Provider-backed realtime transcription connection details."""

    provider: str
    token: str
    expires_in_seconds: int
    sample_rate: int
    audio_format: str
    language: str
    channels: int
    model: str
    keep_alive_interval_seconds: int | None = None
    commit_strategy: str | None = None


async def _create_elevenlabs_realtime_token() -> tuple[str, int]:
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise ValueError("ELEVENLABS_API_KEY not configured")

    async with httpx.AsyncClient(base_url=ELEVENLABS_API_BASE, timeout=15.0) as client:
        response = await client.post(
            "/v1/single-use-token/realtime_scribe",
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        response.raise_for_status()
        payload = response.json()

    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("ElevenLabs returned an invalid realtime transcription token")

    return token, ELEVENLABS_TOKEN_TTL_SECONDS


async def create_realtime_transcription_session(
    *,
    language: str = "multi",
    channels: int = 1,
) -> RealtimeTranscriptionSession:
    """Create a realtime transcription session for the active speech runtime."""
    settings = get_settings()
    provider = settings.speech_to_text_provider.strip().lower()
    resolved_language = language.strip().lower() or "multi"
    resolved_channels = max(1, channels)

    if provider != "elevenlabs":
        raise ValueError(
            f"Unsupported speech_to_text_provider: {provider}. "
            "Only elevenlabs is supported."
        )

    token, expires_in_seconds = await _create_elevenlabs_realtime_token()
    return RealtimeTranscriptionSession(
        provider=provider,
        token=token,
        expires_in_seconds=expires_in_seconds,
        sample_rate=DEFAULT_SAMPLE_RATE,
        audio_format="pcm_16000",
        language=resolved_language,
        channels=resolved_channels,
        model=settings.elevenlabs_realtime_speech_to_text_model,
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
    )
