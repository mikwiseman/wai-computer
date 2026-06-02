"""ElevenLabs custom-LLM bridge routes (hands-free voice, Layer B).

Two endpoints under ``/api/voice/llm``:

- ``POST /session`` — an interactively-authenticated client (not a read-only
  PAT) starts a voice session: we create a fresh conversation and mint a
  short-lived, audience-scoped voice token bound to it. The client hands that
  token to ElevenLabs, which presents it as a Bearer when calling the bridge.
- ``POST /chat/completions`` — the OpenAI-compatible custom-LLM endpoint
  ElevenLabs calls each turn. The voice token identifies the user + conversation
  (the read-only PAT cannot POST to the brain); we run the brain read-only
  (``enable_actions=False`` — hands-free never blind-sends; writes stay behind
  the in-app approval gate) and stream the answer back as chat-completion chunks.

This router is intentionally separate from the existing realtime-voice
``/api/voice/session`` (which returns the ElevenLabs signed URL). Wiring the
minted token into that session + the ElevenLabs agent's custom-LLM config is a
deployment step.
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
from app.core.companion import run_turn
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


@router.post("/session", response_model=VoiceSessionResponse)
async def create_voice_session(user: SessionUser, db: Database) -> VoiceSessionResponse:
    """Start a hands-free voice session: a fresh conversation + a scoped token."""
    conversation = Conversation(user_id=user.id)
    db.add(conversation)
    await db.flush()
    token, ttl = create_voice_session_token(
        user_id=user.id, conversation_id=conversation.id
    )
    await db.commit()
    logger.info(
        "voice session minted user_id=%s conversation_id=%s",
        user.id,
        conversation.id,
    )
    return VoiceSessionResponse(
        token=token,
        conversation_id=str(conversation.id),
        expires_in_seconds=ttl,
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
