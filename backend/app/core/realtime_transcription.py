"""Realtime speech-to-text session minting.

The product has one live STT runtime: Deepgram Nova-3. Native apps connect to
the WaiComputer realtime proxy with a short-lived server-signed token, and the
backend opens Deepgram with the long-lived provider API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt

from app.config import get_settings
from app.core.deepgram import (
    DEEPGRAM_KEEP_ALIVE_INTERVAL_SECONDS,
    DEEPGRAM_REALTIME_CHANNELS,
    DEEPGRAM_REALTIME_ENCODING,
    DEEPGRAM_REALTIME_SAMPLE_RATE,
    build_realtime_websocket_url,
    require_deepgram_api_key,
    validate_deepgram_language,
)
from app.core.deepgram_usage import deepgram_usage_tags
from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    validate_option,
)
from app.models.user import User

REALTIME_PROXY_AUDIENCE = "wai-computer-realtime-transcription"
REALTIME_PROXY_TOKEN_TTL_SECONDS = 60


class UnsupportedRealtimeLanguageError(ValueError):
    """Raised when the requested live STT language is not supported by Nova-3."""


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


@dataclass(frozen=True)
class RealtimeTranscriptionProxyClaims:
    """Validated backend proxy token claims for one realtime STT connection."""

    subject: str
    language: str
    channels: int
    model: str
    purpose: Literal["recording", "dictation"]
    keyterms: list[str] = field(default_factory=list)


def create_realtime_proxy_token(
    *,
    subject: str,
    language: str,
    channels: int,
    model: str,
    purpose: Literal["recording", "dictation"],
    keyterms: list[str] | None = None,
    ttl_seconds: int = REALTIME_PROXY_TOKEN_TTL_SECONDS,
) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "aud": REALTIME_PROXY_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "language": language,
        "channels": channels,
        "model": model,
        "purpose": purpose,
        "keyterms": list(keyterms or []),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl_seconds


def decode_realtime_proxy_token(token: str) -> RealtimeTranscriptionProxyClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=REALTIME_PROXY_AUDIENCE,
        )
    except JWTError as exc:
        raise ValueError("Invalid realtime transcription token") from exc

    subject = payload.get("sub")
    language = payload.get("language")
    model = payload.get("model")
    purpose = payload.get("purpose")
    channels = payload.get("channels")
    keyterms_payload = payload.get("keyterms")

    if not isinstance(subject, str) or not subject:
        raise ValueError("Invalid realtime transcription token subject")
    if not isinstance(language, str) or not language:
        raise ValueError("Invalid realtime transcription token language")
    if not isinstance(model, str) or not model:
        raise ValueError("Invalid realtime transcription token model")
    if purpose not in {"recording", "dictation"}:
        raise ValueError("Invalid realtime transcription token purpose")
    if not isinstance(channels, int) or channels < 1:
        raise ValueError("Invalid realtime transcription token channels")
    if keyterms_payload is None:
        keyterms: list[str] = []
    elif isinstance(keyterms_payload, list) and all(
        isinstance(item, str) for item in keyterms_payload
    ):
        keyterms = keyterms_payload
    else:
        raise ValueError("Invalid realtime transcription token keyterms")

    return RealtimeTranscriptionProxyClaims(
        subject=subject,
        language=validate_deepgram_language(language),
        channels=channels,
        model=model,
        purpose=purpose,
        keyterms=keyterms,
    )


async def _build_deepgram_realtime_session(
    language: str,
    channels: int,
    *,
    model: str,
    purpose: Literal["recording", "dictation"],
    subject: str,
    websocket_url: str,
    keyterms: list[str] | None = None,
) -> RealtimeTranscriptionSession:
    try:
        resolved_language = validate_deepgram_language(language)
    except ValueError as exc:
        raise UnsupportedRealtimeLanguageError(str(exc)) from exc
    resolved_channels = DEEPGRAM_REALTIME_CHANNELS
    del channels
    require_deepgram_api_key()
    token, expires_in = create_realtime_proxy_token(
        subject=subject,
        language=resolved_language,
        channels=resolved_channels,
        purpose=purpose,
        model=model,
        keyterms=keyterms,
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
    websocket_url: str = "ws://localhost:8000/api/transcription/stream",
    keyterms: list[str] | None = None,
) -> RealtimeTranscriptionSession:
    """Create a realtime transcription session for the active speech runtime.

    Dictation and recording use product-managed provider/model defaults. The
    user argument is accepted for API compatibility, but user preferences cannot
    change the selected live STT provider.
    """
    try:
        resolved_language = validate_deepgram_language(language)
    except ValueError as exc:
        raise UnsupportedRealtimeLanguageError(str(exc)) from exc
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
        subject=str(getattr(user, "id", "system")),
        websocket_url=websocket_url,
        keyterms=keyterms,
    )


def build_deepgram_realtime_url_from_proxy_claims(
    claims: RealtimeTranscriptionProxyClaims,
) -> str:
    return build_realtime_websocket_url(
        language=claims.language,
        channels=claims.channels,
        purpose=claims.purpose,
        model=claims.model,
        keyterms=claims.keyterms,
        tags=deepgram_usage_tags(operation="realtime_stream", purpose=claims.purpose),
    )
