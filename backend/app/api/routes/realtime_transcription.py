"""Realtime transcription session routes."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.core.observability import add_sentry_breadcrumb, capture_sentry_exception
from app.core.realtime_transcription import create_realtime_transcription_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcription", tags=["transcription"])


UNAVAILABLE_DETAIL = "Live transcription is temporarily unavailable. Please try again in a moment."


class CreateRealtimeTranscriptionSessionRequest(BaseModel):
    language: str = "multi"
    channels: int = Field(default=1, ge=1, le=2)
    purpose: Literal["recording", "dictation"] = "recording"


class RealtimeTranscriptionSessionResponse(BaseModel):
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
    no_verbatim: bool
    websocket_url: str | None = None
    auth_scheme: str = "query_token"


@router.post("/session", response_model=RealtimeTranscriptionSessionResponse)
async def create_session(
    request: CreateRealtimeTranscriptionSessionRequest,
    user: CurrentUser,
) -> RealtimeTranscriptionSessionResponse:
    """Create a provider-backed realtime speech-to-text session."""
    add_sentry_breadcrumb(
        category="transcription.session",
        message="mint requested",
        data={
            "language": request.language,
            "channels": request.channels,
            "purpose": request.purpose,
        },
    )
    logger.info(
        "creating realtime transcription session user_id=%s language=%s channels=%s purpose=%s",
        user.id,
        request.language,
        request.channels,
        request.purpose,
    )
    try:
        session = await create_realtime_transcription_session(
            language=request.language,
            channels=request.channels,
            purpose=request.purpose,
        )
    except ValueError as exc:
        logger.warning(
            "realtime transcription session unavailable user_id=%s reason=%s purpose=%s",
            user.id,
            str(exc),
            request.purpose,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc
    except Exception as exc:
        capture_sentry_exception(
            exc,
            extras={
                "language": request.language,
                "channels": request.channels,
                "purpose": request.purpose,
            },
        )
        logger.exception(
            "realtime transcription session failed user_id=%s error=%s purpose=%s",
            user.id,
            str(exc),
            request.purpose,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc

    add_sentry_breadcrumb(
        category="transcription.session",
        message="mint succeeded",
        data={
            "provider": session.provider,
            "model": session.model,
            "language": session.language,
            "purpose": request.purpose,
        },
    )
    logger.info(
        "realtime transcription session created user_id=%s provider=%s model=%s purpose=%s",
        user.id,
        session.provider,
        session.model,
        request.purpose,
    )
    return RealtimeTranscriptionSessionResponse(
        provider=session.provider,
        token=session.token,
        expires_in_seconds=session.expires_in_seconds,
        sample_rate=session.sample_rate,
        audio_format=session.audio_format,
        language=session.language,
        channels=session.channels,
        model=session.model,
        keep_alive_interval_seconds=session.keep_alive_interval_seconds,
        commit_strategy=session.commit_strategy,
        no_verbatim=session.no_verbatim,
        websocket_url=session.websocket_url,
        auth_scheme=session.auth_scheme,
    )
