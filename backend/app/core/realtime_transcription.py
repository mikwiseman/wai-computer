"""Realtime speech-to-text session minting.

Two flows live side-by-side:

- **Recording** (long-form library transcription) keeps using ElevenLabs
  Scribe v2 Realtime via the existing `/v1/single-use-token/realtime_scribe`
  endpoint. Migration to Inworld is Phase 7 of the dictation refactor.
- **Dictation** (push-to-talk) uses Inworld's unified STT endpoint with the
  `soniox/stt-rt-v4` model. Inworld auth is HTTP Basic with a base64
  `<id>:<secret>` credential held server-side; the backend issues a
  short-lived session payload to the Swift client which then connects
  directly to `wss://api.inworld.ai`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from app.config import get_settings
from app.core.elevenlabs import ELEVENLABS_API_BASE
from app.core.inworld import build_session as build_inworld_session

ELEVENLABS_TOKEN_TTL_SECONDS = 15 * 60
INWORLD_TOKEN_TTL_SECONDS = 15 * 60  # Inworld credentials don't expire, but
# the Swift client treats the session as short-lived to mirror ElevenLabs.
DEFAULT_SAMPLE_RATE = 16_000

DictationProvider = Literal["elevenlabs", "inworld"]


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
    no_verbatim: bool = True
    websocket_url: str | None = None
    auth_scheme: str = "query_token"  # "query_token" (ElevenLabs) | "basic" (Inworld)


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


def _build_inworld_dictation_session(language: str, channels: int) -> RealtimeTranscriptionSession:
    settings = get_settings()
    if not settings.inworld_api_key:
        raise ValueError("INWORLD_API_KEY not configured")

    inworld = build_inworld_session(
        api_key=settings.inworld_api_key,
        model_id=settings.dictation_stt_model,
        language=language,
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=channels,
    )
    return RealtimeTranscriptionSession(
        provider="inworld",
        token=inworld.auth_header,  # full "Basic <base64>" string
        expires_in_seconds=INWORLD_TOKEN_TTL_SECONDS,
        sample_rate=inworld.sample_rate_hertz,
        audio_format="linear16_16000",
        language=inworld.language,
        channels=inworld.number_of_channels,
        model=inworld.model_id,
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url=inworld.websocket_url,
        auth_scheme="basic",
    )


async def create_realtime_transcription_session(
    *,
    language: str = "multi",
    channels: int = 1,
    purpose: Literal["recording", "dictation"] = "recording",
) -> RealtimeTranscriptionSession:
    """Create a realtime transcription session for the active speech runtime.

    `purpose="dictation"` routes to Inworld + Soniox v4 RT.
    `purpose="recording"` keeps the existing ElevenLabs path until Phase 7.
    """
    settings = get_settings()
    resolved_language = language.strip().lower() or "multi"
    resolved_channels = max(1, channels)

    if purpose == "dictation":
        provider = settings.dictation_stt_provider.strip().lower()
        if provider != "inworld":
            raise ValueError(
                f"Unsupported dictation_stt_provider: {provider}. Only inworld is supported."
            )
        return _build_inworld_dictation_session(resolved_language, resolved_channels)

    # Recording flow — ElevenLabs.
    provider = settings.speech_to_text_provider.strip().lower()
    if provider != "elevenlabs":
        raise ValueError(
            f"Unsupported speech_to_text_provider: {provider}. "
            "Only elevenlabs is supported for the recording flow."
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
        no_verbatim=bool(settings.elevenlabs_no_verbatim),
        websocket_url=None,
        auth_scheme="query_token",
    )
