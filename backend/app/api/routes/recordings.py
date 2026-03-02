"""Recording CRUD routes."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.core.summarizer import summarize_transcript
from app.models.recording import ActionItem, Recording, Summary

router = APIRouter(prefix="/recordings", tags=["recordings"])


class SegmentResponse(BaseModel):
    """Response for a transcript segment."""

    id: str
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None
    confidence: float | None


class SummaryResponse(BaseModel):
    """Response for a recording summary."""

    summary: str | None
    key_points: list[str] | None
    decisions: list[dict] | None
    topics: list[str] | None
    people_mentioned: list[str] | None
    sentiment: str | None


class ActionItemResponse(BaseModel):
    """Response for an action item."""

    id: str
    recording_id: str
    task: str
    owner: str | None
    due_date: str | None
    priority: str | None
    status: str
    source: str
    created_at: str


class RecordingResponse(BaseModel):
    """Response for a recording."""

    id: str
    title: str | None
    type: str
    audio_url: str | None
    duration_seconds: int | None
    language: str | None
    created_at: datetime


class RecordingDetailResponse(RecordingResponse):
    """Detailed response for a recording including segments and summary."""

    segments: list[SegmentResponse]
    summary: SummaryResponse | None
    action_items: list[ActionItemResponse]


class CreateRecordingRequest(BaseModel):
    """Request to create a recording."""

    title: str | None = None
    type: Literal["meeting", "note", "reflection"] = "note"
    language: str = "en"


class UpdateRecordingRequest(BaseModel):
    """Request to update a recording."""

    title: str | None = None
    type: Literal["meeting", "note", "reflection"] | None = None


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    user: CurrentUser,
    db: Database,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type: Literal["meeting", "note", "reflection"] | None = None,
) -> list[RecordingResponse]:
    """List user's recordings."""
    query = select(Recording).where(Recording.user_id == user.id)

    if type:
        query = query.where(Recording.type == type)

    query = query.order_by(Recording.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    recordings = result.scalars().all()

    return [
        RecordingResponse(
            id=str(r.id),
            title=r.title,
            type=r.type,
            audio_url=r.audio_url,
            duration_seconds=r.duration_seconds,
            language=r.language,
            created_at=r.created_at,
        )
        for r in recordings
    ]


@router.post("", response_model=RecordingResponse, status_code=status.HTTP_201_CREATED)
async def create_recording(
    request: CreateRecordingRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """Create a new recording."""
    recording = Recording(
        user_id=user.id,
        title=request.title,
        type=request.type,
        language=request.language,
    )
    db.add(recording)
    await db.flush()

    return RecordingResponse(
        id=str(recording.id),
        title=recording.title,
        type=recording.type,
        audio_url=recording.audio_url,
        duration_seconds=recording.duration_seconds,
        language=recording.language,
        created_at=recording.created_at,
    )


@router.get("/{recording_id}", response_model=RecordingDetailResponse)
async def get_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> RecordingDetailResponse:
    """Get a recording with all details."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(
            selectinload(Recording.segments),
            selectinload(Recording.summary),
            selectinload(Recording.action_items),
        )
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    return RecordingDetailResponse(
        id=str(recording.id),
        title=recording.title,
        type=recording.type,
        audio_url=recording.audio_url,
        duration_seconds=recording.duration_seconds,
        language=recording.language,
        created_at=recording.created_at,
        segments=[
            SegmentResponse(
                id=str(s.id),
                speaker=s.speaker,
                content=s.content,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                confidence=s.confidence,
            )
            for s in sorted(recording.segments, key=lambda x: x.start_ms or 0)
        ],
        summary=SummaryResponse(
            summary=recording.summary.summary,
            key_points=recording.summary.key_points,
            decisions=recording.summary.decisions,
            topics=recording.summary.topics,
            people_mentioned=recording.summary.people_mentioned,
            sentiment=recording.summary.sentiment,
        )
        if recording.summary
        else None,
        action_items=[
            ActionItemResponse(
                id=str(a.id),
                recording_id=str(a.recording_id),
                task=a.task,
                owner=a.owner,
                due_date=a.due_date.isoformat() if a.due_date else None,
                priority=a.priority,
                status=a.status,
                source=a.source,
                created_at=a.created_at.isoformat(),
            )
            for a in recording.action_items
        ],
    )


@router.delete("/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Delete a recording."""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id, Recording.user_id == user.id)
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    await db.delete(recording)


@router.patch("/{recording_id}", response_model=RecordingResponse)
async def update_recording(
    recording_id: UUID,
    request: UpdateRecordingRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """Update a recording."""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id, Recording.user_id == user.id)
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if request.title is not None:
        recording.title = request.title
    if request.type is not None:
        recording.type = request.type

    await db.flush()

    return RecordingResponse(
        id=str(recording.id),
        title=recording.title,
        type=recording.type,
        audio_url=recording.audio_url,
        duration_seconds=recording.duration_seconds,
        language=recording.language,
        created_at=recording.created_at,
    )


@router.get("/{recording_id}/transcript", response_model=list[SegmentResponse])
async def get_transcript(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> list[SegmentResponse]:
    """Get transcript segments for a recording."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.segments))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    return [
        SegmentResponse(
            id=str(s.id),
            speaker=s.speaker,
            content=s.content,
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            confidence=s.confidence,
        )
        for s in sorted(recording.segments, key=lambda x: x.start_ms or 0)
    ]


@router.get("/{recording_id}/summary", response_model=SummaryResponse)
async def get_summary(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SummaryResponse:
    """Get AI summary for a recording."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.summary))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if recording.summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not generated")

    return SummaryResponse(
        summary=recording.summary.summary,
        key_points=recording.summary.key_points,
        decisions=recording.summary.decisions,
        topics=recording.summary.topics,
        people_mentioned=recording.summary.people_mentioned,
        sentiment=recording.summary.sentiment,
    )


@router.post("/{recording_id}/generate-summary", response_model=SummaryResponse)
async def generate_summary(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SummaryResponse:
    """Generate or regenerate AI summary for a recording."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.segments), selectinload(Recording.summary))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not recording.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcript segments to summarize",
        )

    # Build transcript text
    transcript_lines = []
    for segment in sorted(recording.segments, key=lambda x: x.start_ms or 0):
        speaker = segment.speaker or "Speaker"
        transcript_lines.append(f"{speaker}: {segment.content}")
    transcript = "\n".join(transcript_lines)

    # Generate summary
    summary_result = await summarize_transcript(transcript)

    # Update or create summary
    if recording.summary:
        recording.summary.summary = summary_result.summary
        recording.summary.key_points = summary_result.key_points
        recording.summary.decisions = summary_result.decisions
        recording.summary.topics = summary_result.topics
        recording.summary.people_mentioned = summary_result.people_mentioned
        recording.summary.sentiment = summary_result.sentiment
    else:
        summary = Summary(
            recording_id=recording.id,
            summary=summary_result.summary,
            key_points=summary_result.key_points,
            decisions=summary_result.decisions,
            topics=summary_result.topics,
            people_mentioned=summary_result.people_mentioned,
            sentiment=summary_result.sentiment,
        )
        db.add(summary)
        recording.summary = summary

    # Update title if not set
    if not recording.title:
        recording.title = summary_result.title

    # Replace previously generated action items on regeneration.
    await db.execute(
        delete(ActionItem).where(
            ActionItem.recording_id == recording.id,
            ActionItem.source == "generated",
        )
    )

    # Create action items
    for item in summary_result.action_items:
        task = str(item.get("task", "")).strip()
        if not task:
            continue

        due_raw = item.get("due")
        due_date: date | None = None
        if isinstance(due_raw, date):
            due_date = due_raw
        elif isinstance(due_raw, str) and due_raw:
            try:
                due_date = date.fromisoformat(due_raw)
            except ValueError:
                due_date = None

        priority = item.get("priority", "medium")
        if priority not in {"high", "medium", "low"}:
            priority = "medium"

        action = ActionItem(
            recording_id=recording.id,
            task=task,
            owner=item.get("owner"),
            due_date=due_date,
            priority=priority,
            source="generated",
        )
        db.add(action)

    await db.flush()

    return SummaryResponse(
        summary=recording.summary.summary,
        key_points=recording.summary.key_points,
        decisions=recording.summary.decisions,
        topics=recording.summary.topics,
        people_mentioned=recording.summary.people_mentioned,
        sentiment=recording.summary.sentiment,
    )
