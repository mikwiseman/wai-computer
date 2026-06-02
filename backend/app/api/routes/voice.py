"""Custom-LLM bridge routes for the voice-agent orchestrator (hands-free, Layer B).

The orchestrator is **Deepgram Voice Agent** (one WebSocket: listen→think→speak,
built-in barge-in), pointed at our brain via its OpenAI-compatible ``think``
endpoint. The same endpoint is vendor-agnostic — any OpenAI-compatible
orchestrator (e.g. ElevenLabs Conversational AI) works too — so ElevenLabs, if
used at all, is only a swappable Russian TTS *voice*, not the brain.

Two endpoints under ``/api/voice/llm``:

- ``POST /session`` — an interactively-authenticated client (not a read-only
  PAT) starts a voice session: we create a fresh conversation, mint a
  short-lived, audience-scoped voice token bound to it, and return the Deepgram
  Voice Agent ``Settings`` (with ``think`` already pointed at this bridge +
  the token as a Bearer header). The client sends those settings to Deepgram.
- ``POST /chat/completions`` — the OpenAI-compatible custom-LLM endpoint the
  orchestrator calls each turn. The voice token identifies the user +
  conversation (the read-only PAT cannot POST to the brain); we run the brain
  read-only (``enable_actions=False`` — hands-free never blind-sends; writes
  stay behind the in-app approval gate) and stream the answer back as
  chat-completion chunks.

Separate from the existing realtime-voice ``/api/voice/session``. The Deepgram
WebSocket URL + Deepgram auth token are client/deploy concerns; Russian voice
output needs a non-Deepgram TTS voice configured (Aura has no Russian).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.api.deps import Database, SessionUser
from app.config import get_settings
from app.core.companion import run_turn
from app.core.deepgram_voice_agent import (
    BRIDGE_PATH,
    UnsupportedVoiceLanguageError,
    build_voice_agent_settings,
)
from app.core.voice_bridge import VoiceChatCompletionRequest, to_chat_completion_sse
from app.core.voice_session import (
    VoiceSessionClaims,
    VoiceTokenError,
    create_voice_session_token,
    decode_voice_session_token,
)
from app.models.companion import Conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice/llm", tags=["voice"])

_voice_bearer = HTTPBearer(auto_error=False)


async def _voice_claims(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_voice_bearer)
    ],
) -> VoiceSessionClaims:
    """Resolve the per-session voice token to its claims (fail-closed)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing voice token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_voice_session_token(credentials.credentials)
    except VoiceTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid voice token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


class VoiceSessionResponse(BaseModel):
    token: str
    conversation_id: str
    expires_in_seconds: int
    # Ready-to-send Deepgram Voice Agent Settings (think already points here).
    voice_agent_settings: dict


@router.post("/session", response_model=VoiceSessionResponse)
async def create_voice_session(
    user: SessionUser, db: Database, language: str = "en"
) -> VoiceSessionResponse:
    """Start a hands-free voice session: a fresh conversation, a scoped token,
    and the Deepgram Voice Agent settings the client streams to Deepgram."""
    settings = get_settings()
    bridge_url = f"{settings.frontend_url.rstrip('/')}{BRIDGE_PATH}"

    conversation = Conversation(user_id=user.id)
    db.add(conversation)
    await db.flush()
    token, ttl = create_voice_session_token(
        user_id=user.id, conversation_id=conversation.id
    )
    try:
        voice_agent_settings = build_voice_agent_settings(
            bridge_url=bridge_url, voice_token=token, language=language
        )
    except UnsupportedVoiceLanguageError as exc:
        # e.g. Russian: Deepgram Aura can't speak it and no voice is configured.
        # Surface it rather than emitting a wrong-language voice (no fallback).
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No voice configured for language '{language}'. Use push-to-talk "
                "(on-device TTS) or configure a non-Deepgram voice for this language."
            ),
        ) from exc
    await db.commit()
    logger.info(
        "voice session minted user_id=%s conversation_id=%s language=%s",
        user.id,
        conversation.id,
        language,
    )
    return VoiceSessionResponse(
        token=token,
        conversation_id=str(conversation.id),
        expires_in_seconds=ttl,
        voice_agent_settings=voice_agent_settings,
    )


async def _empty_event_stream() -> AsyncIterator[Any]:
    """An async iterator that yields nothing — used when there is no user turn,
    so the bridge still emits a valid empty completion."""
    if False:  # pragma: no cover
        yield


@router.post("/chat/completions")
async def chat_completions(
    request: VoiceChatCompletionRequest,
    claims: Annotated[VoiceSessionClaims, Depends(_voice_claims)],
    db: Database,
) -> StreamingResponse:
    """OpenAI-compatible custom-LLM endpoint ElevenLabs calls each turn."""
    user_text = request.latest_user_message()
    response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    logger.info(
        "voice turn user_id=%s conversation_id=%s has_user_text=%s",
        claims.user_id,
        claims.conversation_id,
        user_text is not None,
    )

    async def event_stream() -> AsyncIterator[str]:
        if user_text is None:
            events: AsyncIterator[Any] = _empty_event_stream()
        else:
            events = run_turn(
                db,
                claims.user_id,
                claims.conversation_id,
                user_text,
                enable_actions=False,
            )
        async for line in to_chat_completion_sse(events, response_id=response_id):
            yield line

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
