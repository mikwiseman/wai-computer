"""Per-session voice token for the ElevenLabs custom-LLM bridge.

The read-only ``wc_live_`` PAT cannot POST to the brain, and a long-lived
credential should never reach a third party (ElevenLabs). Instead an
authenticated client mints a short-lived token, scoped via JWT ``audience`` to
the voice bridge and bound to one conversation; the bridge verifies it on every
chat-completions call and runs the brain for that user + conversation only.

Mirrors the realtime-transcription proxy-token pattern (audience isolation +
explicit claim validation, ``jose``). Fail-closed: any malformed, expired,
mis-scoped, or tampered token raises ``VoiceTokenError``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings

VOICE_LLM_AUDIENCE = "wai-voice-llm"
VOICE_TOKEN_TTL_SECONDS = 1800  # one 30-minute voice session


class VoiceTokenError(ValueError):
    """A voice token is missing, malformed, expired, or mis-scoped."""


@dataclass(frozen=True)
class VoiceSessionClaims:
    user_id: uuid.UUID
    conversation_id: uuid.UUID


def create_voice_session_token(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    ttl_seconds: int = VOICE_TOKEN_TTL_SECONDS,
) -> tuple[str, int]:
    """Mint a voice-bridge token for one user + conversation. Returns the token
    and its TTL in seconds."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "aud": VOICE_LLM_AUDIENCE,
        "cid": str(conversation_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl_seconds


def decode_voice_session_token(token: str) -> VoiceSessionClaims:
    """Verify a voice-bridge token and return its claims. Raises
    ``VoiceTokenError`` on any failure (expiry and audience are enforced by the
    decoder)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=VOICE_LLM_AUDIENCE,
        )
    except JWTError as exc:
        raise VoiceTokenError("invalid voice token") from exc

    subject = payload.get("sub")
    conversation = payload.get("cid")
    if not isinstance(subject, str) or not subject:
        raise VoiceTokenError("invalid voice token subject")
    if not isinstance(conversation, str) or not conversation:
        raise VoiceTokenError("invalid voice token conversation")
    try:
        return VoiceSessionClaims(
            user_id=uuid.UUID(subject),
            conversation_id=uuid.UUID(conversation),
        )
    except ValueError as exc:
        raise VoiceTokenError("malformed voice token ids") from exc
