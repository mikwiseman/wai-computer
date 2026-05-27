"""Realtime speech-to-text session minting.

The product has one live STT runtime: OpenAI gpt-realtime-whisper. The native
apps connect directly to the provider WebSocket with a short-lived server-minted
token, so clients never receive the long-lived provider API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.openai_transcription import (
    OPENAI_REALTIME_SAMPLE_RATE,
    OPENAI_REALTIME_TOKEN_TTL_SECONDS,
    create_realtime_client_secret,
    realtime_websocket_url,
)
from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User


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
    auth_scheme: str = "bearer"


async def _build_openai_realtime_session(
    language: str,
    channels: int,
    *,
    model: str,
) -> RealtimeTranscriptionSession:
    token = await create_realtime_client_secret(
        model=model,
        language=language,
    )
    del channels
    return RealtimeTranscriptionSession(
        provider="openai",
        token=token,
        expires_in_seconds=OPENAI_REALTIME_TOKEN_TTL_SECONDS,
        sample_rate=OPENAI_REALTIME_SAMPLE_RATE,
        audio_format="pcm_24000",
        language=language,
        channels=1,
        model=model,
        keep_alive_interval_seconds=None,
        commit_strategy="manual",
        no_verbatim=False,
        websocket_url=realtime_websocket_url(model),
        auth_scheme="bearer",
    )


async def create_realtime_transcription_session(
    *,
    language: str = "multi",
    channels: int = 1,
    purpose: Literal["recording", "dictation"] = "recording",
    user: User | None = None,
) -> RealtimeTranscriptionSession:
    """Create a realtime transcription session for the active speech runtime.

    Dictation and recording use product-managed provider/model defaults. The
    user argument is accepted for API compatibility, but user preferences cannot
    change the selected live STT provider.
    """
    del user

    resolved_language = language.strip().lower() or "multi"
    # OpenAI Realtime transcription docs specify mono PCM for audio/pcm.
    resolved_channels = 1
    del channels

    if purpose == "dictation":
        provider, model = validate_option(
            "dictation_live_stt",
            DEFAULT_DICTATION_LIVE_STT_PROVIDER,
            DEFAULT_DICTATION_LIVE_STT_MODEL,
        )
        unsupported_message = f"Unsupported dictation_live_stt_provider: {provider}."
    else:
        provider, model = validate_option(
            "recording_live_stt",
            DEFAULT_RECORDING_LIVE_STT_PROVIDER,
            DEFAULT_RECORDING_LIVE_STT_MODEL,
        )
        unsupported_message = f"Unsupported recording_live_stt_provider: {provider}."

    if provider != "openai":
        raise ValueError(unsupported_message)

    return await _build_openai_realtime_session(
        resolved_language,
        resolved_channels,
        model=model,
    )
