"""Stateless QA route for conversational Q&A against recordings."""

import logging
import uuid

import sentry_sdk
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database
from app.core.qa import QAResult, ask_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["qa"])


class QARequest(BaseModel):
    """Request to send a QA question."""
    question: str = Field(min_length=1)
    recording_ids: list[str] | None = None


class SourceResponse(BaseModel):
    """A source segment in the QA response."""
    segment_id: str
    recording_id: str
    recording_title: str | None
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None


class QAResponse(BaseModel):
    """Response from the QA endpoint."""
    answer: str
    sources: list[SourceResponse]


@router.post("", response_model=QAResponse)
async def ask_question(
    request: QARequest,
    user: CurrentUser,
    db: Database,
) -> QAResponse:
    """Send a question and get a RAG-powered answer from meeting transcripts."""
    logger.info(
        "ask_question user_id=%s question_len=%d",
        user.id, len(request.question),
    )
    sentry_sdk.add_breadcrumb(
        category="qa",
        message="QA question sent",
        data={
            "has_recording_filter": bool(request.recording_ids),
        },
        level="info",
    )
    try:
        recording_ids = (
            [uuid.UUID(rid) for rid in request.recording_ids]
            if request.recording_ids
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid UUID: {exc}",
        ) from exc

    result: QAResult = await ask_database(
        db=db,
        user_id=user.id,
        question=request.question,
        recording_ids=recording_ids,
    )

    return QAResponse(
        answer=result.answer,
        sources=[
            SourceResponse(
                segment_id=s.segment_id,
                recording_id=s.recording_id,
                recording_title=s.recording_title,
                speaker=s.speaker,
                content=s.content,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
            )
            for s in result.source_segments
        ],
    )
