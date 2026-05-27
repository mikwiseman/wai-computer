"""Realtime speech-to-text session minting.

The product has one live STT runtime: Deepgram Nova-3. Native apps connect
directly to the provider WebSocket with a short-lived server-minted token, so
clients never receive the long-lived provider API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.deepgram import (
    DEEPGRAM_KEEP_ALIVE_INTERVAL_SECONDS,
    DEEPGRAM_REALTIME_CHANNELS,
    DEEPGRAM_REALTIME_ENCODING,
    DEEPGRAM_REALTIME_SAMPLE_RATE,
    build_realtime_websocket_url,
    create_temporary_token,
    normalize_deepgram_language,
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


async def _build_deepgram_realtime_session(
    language: str,
    channels: int,
    *,
    model: str,
    purpose: Literal["recording", "dictation"],
) -> RealtimeTranscriptionSession:
    resolved_language = normalize_deepgram_language(language)
    resolved_channels = DEEPGRAM_REALTIME_CHANNELS
    del channels
    token, expires_in = await create_temporary_token()
    websocket_url = build_realtime_websocket_url(
        language=resolved_language,
        channels=resolved_channels,
        purpose=purpose,
        model=model,
    )
    return RealtimeTranscriptionSession(
        provider="deepgram",
        token=token,
        expires_in_seconds=expires_in,
        sample_rate=DEEPGRAM_REALTIME_SAMPLE_RATE,
        audio_format=DEEPGRAM_REALTIME_ENCODING,
        language=resolved_language,
        channels=resolved_channels,
        model=model,
        keep_alive_interval_seconds=DEEPGRAM_KEEP_ALIVE_INTERVAL_SECONDS,
        commit_strategy=None,
        no_verbatim=False,
        websocket_url=websocket_url,
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

    resolved_language = normalize_deepgram_language(language)
    resolved_channels = DEEPGRAM_REALTIME_CHANNELS

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

    if provider != "deepgram":
        raise ValueError(unsupported_message)

    return await _build_deepgram_realtime_session(
        resolved_language,
        resolved_channels,
        model=model,
        purpose=purpose,
    )
