"""Realtime voice session routes."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.voice_runtime import create_realtime_voice_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


UNAVAILABLE_DETAIL = "Voice mode is temporarily unavailable. Please try again in a moment."


class CreateRealtimeVoiceSessionRequest(BaseModel):
    mode: Literal["conversation", "recording"] = "conversation"
    agent_id: str | None = None
    include_conversation_id: bool = False
    branch_id: str | None = None
    environment: str | None = None


class RealtimeVoiceSessionResponse(BaseModel):
    provider: str
    mode: str
    agent_id: str
    signed_url: str
    expires_in_seconds: int
    environment: str | None = None
    branch_id: str | None = None


@router.post("/session", response_model=RealtimeVoiceSessionResponse)
async def create_session(
    request: CreateRealtimeVoiceSessionRequest,
    user: CurrentUser,
) -> RealtimeVoiceSessionResponse:
    """Create a provider-backed realtime voice session for the current user."""
    logger.info(
        "creating realtime voice session user_id=%s mode=%s branch_id=%s",
        user.id,
        request.mode,
        request.branch_id,
    )
    try:
        session = await create_realtime_voice_session(
            mode=request.mode,
            agent_id=request.agent_id,
            include_conversation_id=request.include_conversation_id,
            branch_id=request.branch_id,
            environment=request.environment,
        )
    except ValueError as exc:
        logger.warning(
            "realtime voice session unavailable user_id=%s mode=%s reason=%s",
            user.id,
            request.mode,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc
    except Exception as exc:
        logger.error(
            "realtime voice session failed user_id=%s mode=%s error=%s",
            user.id,
            request.mode,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc

    logger.info(
        "realtime voice session created user_id=%s provider=%s mode=%s agent_id=%s",
        user.id,
        session.provider,
        session.mode,
        session.agent_id,
    )

    return RealtimeVoiceSessionResponse(
        provider=session.provider,
        mode=session.mode,
        agent_id=session.agent_id,
        signed_url=session.signed_url,
        expires_in_seconds=session.expires_in_seconds,
        environment=session.environment,
        branch_id=session.branch_id,
    )
