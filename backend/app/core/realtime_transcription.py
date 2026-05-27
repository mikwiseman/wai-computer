"""Realtime speech-to-text session minting.

The product has one live STT runtime: Inworld STT-1. The native apps connect
directly to the provider WebSocket with a short-lived server-minted token, so
clients never receive the long-lived provider API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import get_settings
from app.core.inworld import build_session as build_inworld_session
from app.core.inworld import mint_client_jwt as mint_inworld_client_jwt
from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User

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
    no_verbatim: bool = True
    websocket_url: str | None = None
    auth_scheme: str = "query_token"


async def _build_inworld_realtime_session(
    language: str,
    channels: int,
    *,
    model: str,
) -> RealtimeTranscriptionSession:
    settings = get_settings()
    if not settings.inworld_api_key:
        raise ValueError("INWORLD_API_KEY not configured")

    jwt = await mint_inworld_client_jwt(
        api_key=settings.inworld_api_key,
        workspace=settings.inworld_workspace,
    )
    inworld = build_inworld_session(
        api_key=settings.inworld_api_key,
        auth_header=f"Bearer {jwt.token}",
        expires_in_seconds=jwt.expires_in_seconds,
        model_id=model,
        language=language,
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=channels,
    )
    return RealtimeTranscriptionSession(
        provider="inworld",
        token=jwt.token,
        expires_in_seconds=inworld.expires_in_seconds,
        sample_rate=inworld.sample_rate_hertz,
        audio_format="linear16_16000",
        language=inworld.language,
        channels=inworld.number_of_channels,
        model=inworld.model_id,
        keep_alive_interval_seconds=None,
        commit_strategy="vad",
        no_verbatim=False,
        websocket_url=inworld.websocket_url,
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
    resolved_channels = max(1, channels)

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

    if provider != "inworld":
        raise ValueError(unsupported_message)

    return await _build_inworld_realtime_session(
        resolved_language,
        resolved_channels,
        model=model,
    )
