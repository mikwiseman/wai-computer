"""Realtime speech-to-text session minting.

The product has two live STT runtimes behind one client wire protocol:

- **Dictation** → OpenAI ``gpt-realtime-whisper`` (the realtime proxy
  translates the client protocol to OpenAI realtime events).
- **Recording** → Deepgram Nova-3 (transparent proxy bridge, diarization).

Native apps connect to the WaiComputer realtime proxy with a short-lived
server-signed token; the backend opens the upstream provider with the
long-lived API key. The proxy token carries the provider so the stream route
knows which upstream to dial.
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
from app.core.openai_realtime import (
    OPENAI_REALTIME_CHANNELS,
    OPENAI_REALTIME_ENCODING,
    OPENAI_REALTIME_SAMPLE_RATE,
    require_openai_api_key,
)
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
PRODUCT_REALTIME_KEYTERMS = (
    "WaiComputer",
    "Wai Computer",
    "ВайКомпьютер",
    "Вай Компьютер",
)
PRODUCT_REALTIME_REPLACEMENTS = (
    ("wai computer", "WaiComputer"),
    ("вай компьютер", "WaiComputer"),
    ("вайкомпьютер", "WaiComputer"),
    ("во ecomputer", "WaiComputer"),
    ("ecomputer", "WaiComputer"),
    # gpt-realtime-whisper renderings of the spoken brand ("вай" heard as
    # "в и"/"вои"/"вый"). Multi-word finds are safe: replacements match whole
    # phrases with word boundaries.
    ("в и компьютер", "WaiComputer"),
    ("в икомпьютер", "WaiComputer"),
    ("вай-компьютер", "WaiComputer"),
    ("way computer", "WaiComputer"),
    ("вои компьютер", "WaiComputer"),
    ("вый компьютер", "WaiComputer"),
    ("в icomputer", "WaiComputer"),
    ("icomputer", "WaiComputer"),
)


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
    provider: str = "deepgram"
    keyterms: list[str] = field(default_factory=list)
    replacements: list[tuple[str, str]] = field(default_factory=list)


def _merge_realtime_keyterms(keyterms: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for term in (*PRODUCT_REALTIME_KEYTERMS, *(keyterms or [])):
        clean = term.strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(clean)
    return merged


def _merge_realtime_replacements(
    replacements: list[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    seen: set[str] = set()
    for find, replace in (*PRODUCT_REALTIME_REPLACEMENTS, *(replacements or [])):
        find_clean = find.strip()
        replace_clean = replace.strip()
        if not find_clean or not replace_clean:
            continue
        key = find_clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append((find_clean, replace_clean))
    return merged


def create_realtime_proxy_token(
    *,
    subject: str,
    language: str,
    channels: int,
    model: str,
    purpose: Literal["recording", "dictation"],
    provider: str = "deepgram",
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
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
        "provider": provider,
        "keyterms": list(keyterms or []),
        "replacements": [
            {"find": find, "replace": replace}
            for find, replace in list(replacements or [])
        ],
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
    provider = payload.get("provider", "deepgram")
    channels = payload.get("channels")
    keyterms_payload = payload.get("keyterms")
    replacements_payload = payload.get("replacements")

    if not isinstance(subject, str) or not subject:
        raise ValueError("Invalid realtime transcription token subject")
    if not isinstance(language, str) or not language:
        raise ValueError("Invalid realtime transcription token language")
    if not isinstance(model, str) or not model:
        raise ValueError("Invalid realtime transcription token model")
    if purpose not in {"recording", "dictation"}:
        raise ValueError("Invalid realtime transcription token purpose")
    if provider not in {"deepgram", "openai"}:
        raise ValueError("Invalid realtime transcription token provider")
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
    if replacements_payload is None:
        replacements: list[tuple[str, str]] = []
    elif isinstance(replacements_payload, list):
        replacements = []
        for item in replacements_payload:
            if not isinstance(item, dict):
                raise ValueError("Invalid realtime transcription token replacements")
            find = item.get("find")
            replace = item.get("replace")
            if not isinstance(find, str) or not isinstance(replace, str):
                raise ValueError("Invalid realtime transcription token replacements")
            replacements.append((find, replace))
    else:
        raise ValueError("Invalid realtime transcription token replacements")

    if provider == "deepgram":
        resolved_language = validate_deepgram_language(language)
    else:
        resolved_language = language.strip().lower() or "multi"

    return RealtimeTranscriptionProxyClaims(
        subject=subject,
        language=resolved_language,
        channels=channels,
        model=model,
        purpose=purpose,
        provider=provider,
        keyterms=keyterms,
        replacements=replacements,
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
    replacements: list[tuple[str, str]] | None = None,
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
        provider="deepgram",
        keyterms=_merge_realtime_keyterms(keyterms),
        replacements=_merge_realtime_replacements(replacements),
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


async def _build_openai_realtime_session(
    language: str,
    *,
    model: str,
    purpose: Literal["recording", "dictation"],
    subject: str,
    websocket_url: str,
    keyterms: list[str] | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> RealtimeTranscriptionSession:
    """Mint a proxy session that the stream route bridges to OpenAI realtime.

    The wire contract toward clients is unchanged (binary PCM16 frames +
    ``Finalize``/``CloseStream`` control messages, Results frames back); only
    the sample rate moves to OpenAI's required 24 kHz. gpt-realtime-whisper
    has no keyterm prompting — vocabulary hints live in the cleanup pass —
    but find/replace hints are applied by the proxy to outgoing transcripts.
    """
    resolved_language = language.strip().lower() or "multi"
    require_openai_api_key()
    token, expires_in = create_realtime_proxy_token(
        subject=subject,
        language=resolved_language,
        channels=OPENAI_REALTIME_CHANNELS,
        purpose=purpose,
        model=model,
        provider="openai",
        keyterms=_merge_realtime_keyterms(keyterms),
        replacements=_merge_realtime_replacements(replacements),
    )
    return RealtimeTranscriptionSession(
        provider="openai",
        token=token,
        expires_in_seconds=expires_in,
        sample_rate=OPENAI_REALTIME_SAMPLE_RATE,
        audio_format=OPENAI_REALTIME_ENCODING,
        language=resolved_language,
        channels=OPENAI_REALTIME_CHANNELS,
        model=model,
        keep_alive_interval_seconds=None,
        commit_strategy="manual",
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
    replacements: list[tuple[str, str]] | None = None,
) -> RealtimeTranscriptionSession:
    """Create a realtime transcription session for the active speech runtime.

    Dictation and recording use product-managed provider/model defaults. The
    user argument is accepted for API compatibility, but user preferences cannot
    change the selected live STT provider.
    """
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

    subject = str(getattr(user, "id", "system"))

    if provider == "openai":
        return await _build_openai_realtime_session(
            language,
            model=model,
            purpose=purpose,
            subject=subject,
            websocket_url=websocket_url,
            keyterms=keyterms,
            replacements=replacements,
        )

    if provider != "deepgram":
        raise ValueError(unsupported_message)

    try:
        resolved_language = validate_deepgram_language(language)
    except ValueError as exc:
        raise UnsupportedRealtimeLanguageError(str(exc)) from exc

    return await _build_deepgram_realtime_session(
        resolved_language,
        DEEPGRAM_REALTIME_CHANNELS,
        model=model,
        purpose=purpose,
        subject=subject,
        websocket_url=websocket_url,
        keyterms=keyterms,
        replacements=replacements,
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
        replacements=claims.replacements,
    )
