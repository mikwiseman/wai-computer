"""Realtime transcription session routes."""

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.core.realtime_transcription import create_realtime_transcription_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcription", tags=["transcription"])


UNAVAILABLE_DETAIL = "Live transcription is temporarily unavailable. Please try again in a moment."


class CreateRealtimeTranscriptionSessionRequest(BaseModel):
    language: str = "multi"
    channels: int = Field(default=1, ge=1, le=2)


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


@router.post("/session", response_model=RealtimeTranscriptionSessionResponse)
async def create_session(
    request: CreateRealtimeTranscriptionSessionRequest,
    user: CurrentUser,
) -> RealtimeTranscriptionSessionResponse:
    """Create a provider-backed realtime speech-to-text session."""
    logger.info(
        "creating realtime transcription session user_id=%s language=%s channels=%s",
        user.id,
        request.language,
        request.channels,
    )
    try:
        session = await create_realtime_transcription_session(
            language=request.language,
            channels=request.channels,
        )
    except ValueError as exc:
        logger.warning(
            "realtime transcription session unavailable user_id=%s reason=%s",
            user.id,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        ) from exc
    except Exception as exc:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
        logger.error(
            "realtime transcription session failed user_id=%s error=%s",
            user.id,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{UNAVAILABLE_DETAIL} ({str(exc)})",
        ) from exc

    logger.info(
        "realtime transcription session created user_id=%s provider=%s model=%s",
        user.id,
        session.provider,
        session.model,
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
    )
