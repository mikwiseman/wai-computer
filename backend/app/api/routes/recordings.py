"""Recording CRUD routes."""

import json
import logging
from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.core.deepgram import transcribe_audio_file
from app.core.embeddings import generate_embedding
from app.core.storage import get_storage_client
from app.core.summarizer import summarize_transcript
from app.models.recording import ActionItem, Folder, Recording, Segment, Summary

logger = logging.getLogger(__name__)

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
    folder_id: str | None
    deleted_at: datetime | None
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
    language: str | None = None
    folder_id: UUID | None = None

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()
        return normalized or None


class UpdateRecordingRequest(BaseModel):
    """Request to update a recording."""

    title: str | None = None
    type: Literal["meeting", "note", "reflection"] | None = None
    folder_id: UUID | None = None


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str


def _serialize_summary(summary: Summary | None) -> SummaryResponse | None:
    if summary is None:
        return None

    return SummaryResponse(
        summary=summary.summary,
        key_points=summary.key_points,
        decisions=summary.decisions,
        topics=summary.topics,
        people_mentioned=summary.people_mentioned,
        sentiment=summary.sentiment,
    )


def _serialize_action_item(action_item: ActionItem) -> ActionItemResponse:
    return ActionItemResponse(
        id=str(action_item.id),
        recording_id=str(action_item.recording_id),
        task=action_item.task,
        owner=action_item.owner,
        due_date=action_item.due_date.isoformat() if action_item.due_date else None,
        priority=action_item.priority,
        status=action_item.status,
        source=action_item.source,
        created_at=action_item.created_at.isoformat(),
    )


def _serialize_recording(recording: Recording) -> RecordingResponse:
    return RecordingResponse(
        id=str(recording.id),
        title=recording.title,
        type=recording.type,
        audio_url=recording.audio_url,
        duration_seconds=recording.duration_seconds,
        language=recording.language,
        folder_id=str(recording.folder_id) if recording.folder_id else None,
        deleted_at=recording.deleted_at,
        created_at=recording.created_at,
    )


def _serialize_recording_detail(recording: Recording) -> RecordingDetailResponse:
    return RecordingDetailResponse(
        **_serialize_recording(recording).model_dump(),
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
        summary=_serialize_summary(recording.summary),
        action_items=[_serialize_action_item(a) for a in recording.action_items],
    )


async def _require_folder(
    folder_id: UUID | None,
    user_id: UUID,
    db: Database,
) -> Folder | None:
    if folder_id is None:
        return None

    folder_result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    folder = folder_result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    return folder


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    user: CurrentUser,
    db: Database,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type: Literal["meeting", "note", "reflection"] | None = None,
    folder_id: UUID | None = None,
    trashed: bool = False,
) -> list[RecordingResponse]:
    """List user's recordings."""
    query = select(Recording).where(Recording.user_id == user.id)

    if trashed:
        query = query.where(Recording.deleted_at.is_not(None))
    else:
        query = query.where(Recording.deleted_at.is_(None))

    if type:
        query = query.where(Recording.type == type)
    if folder_id is not None:
        query = query.where(Recording.folder_id == folder_id)

    query = query.order_by(Recording.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    recordings = result.scalars().all()

    return [_serialize_recording(recording) for recording in recordings]


@router.post("", response_model=RecordingResponse, status_code=status.HTTP_201_CREATED)
async def create_recording(
    request: CreateRecordingRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """Create a new recording."""
    language = request.language if request.language is not None else user.default_language
    folder = await _require_folder(request.folder_id, user.id, db)
    recording = Recording(
        user_id=user.id,
        title=request.title,
        type=request.type,
        language=language,
        folder_id=folder.id if folder else None,
    )
    db.add(recording)
    await db.flush()

    return _serialize_recording(recording)


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

    return _serialize_recording_detail(recording)


@router.delete("/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    permanent: bool = False,
) -> None:
    """Delete a recording."""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id, Recording.user_id == user.id)
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if permanent or recording.deleted_at is not None:
        await db.delete(recording)
        return

    recording.deleted_at = datetime.now(timezone.utc)


@router.post("/{recording_id}/restore", response_model=RecordingResponse)
async def restore_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """Restore a recording from trash."""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id, Recording.user_id == user.id)
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    recording.deleted_at = None
    await db.flush()
    return _serialize_recording(recording)


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
    if "folder_id" in request.model_fields_set:
        folder = await _require_folder(request.folder_id, user.id, db)
        recording.folder_id = folder.id if folder else None

    await db.flush()

    return _serialize_recording(recording)


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

    summary = _serialize_summary(recording.summary)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not generated")
    return summary


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

    summary = _serialize_summary(recording.summary)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Summary not saved",
        )
    return summary


ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "ogg", "webm", "opus", "flac"}
EXTENSION_TO_CONTENT_TYPE = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "opus": "audio/opus",
    "flac": "audio/flac",
}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/{recording_id}/upload", response_model=RecordingDetailResponse)
async def upload_audio_file(
    recording_id: UUID,
    file: UploadFile,
    user: CurrentUser,
    db: Database,
    segments_json: str | None = Form(None),
) -> RecordingDetailResponse:
    """Upload an audio file to an existing recording.

    If ``segments_json`` is provided (JSON array of transcript segments from
    a direct Deepgram connection), those segments are stored and server-side
    transcription is skipped.  Each segment object should have: ``text``,
    ``speaker`` (optional), ``start_ms``, ``end_ms``, ``confidence`` (optional).

    If ``segments_json`` is omitted, the audio is transcribed server-side via
    the Deepgram REST API (legacy behaviour).
    """
    # Validate recording exists and belongs to user
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

    # Validate file extension
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '.{ext}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}",
        )

    # Read file data and validate size
    audio_data = await file.read()
    if len(audio_data) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)}MB",
        )

    content_type = EXTENSION_TO_CONTENT_TYPE.get(ext, "application/octet-stream")

    # Upload to S3
    storage = get_storage_client()
    s3_key = await storage.upload_audio(audio_data, user.id, recording_id, content_type)
    recording.audio_url = s3_key

    # Parse client-provided segments or transcribe server-side
    client_segments: list[dict] | None = None
    if segments_json is not None:
        client_segments = json.loads(segments_json)

    if client_segments is not None:
        # Client already transcribed via direct Deepgram connection
        for seg in client_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            embedding = None
            try:
                embedding = await generate_embedding(text)
            except Exception as e:
                logger.warning(f"Failed to generate embedding: {e}")

            db.add(
                Segment(
                    recording_id=recording_id,
                    speaker=seg.get("speaker"),
                    content=text,
                    start_ms=seg.get("start_ms", 0),
                    end_ms=seg.get("end_ms", 0),
                    confidence=seg.get("confidence"),
                    embedding=embedding,
                )
            )

        # Update duration from last segment
        end_times = [s.get("end_ms", 0) for s in client_segments if s.get("text", "").strip()]
        if end_times:
            recording.duration_seconds = max(end_times) // 1000
    else:
        # Transcribe via Deepgram REST API (legacy / file-upload path)
        transcript_results = await transcribe_audio_file(
            audio_data, language=recording.language or "en", content_type=content_type
        )

        for tr in transcript_results:
            embedding = None
            if tr.text.strip():
                try:
                    embedding = await generate_embedding(tr.text)
                except Exception as e:
                    logger.warning(f"Failed to generate embedding: {e}")

            db.add(
                Segment(
                    recording_id=recording_id,
                    speaker=tr.speaker,
                    content=tr.text,
                    start_ms=tr.start_ms,
                    end_ms=tr.end_ms,
                    confidence=tr.confidence,
                    embedding=embedding,
                )
            )

        if transcript_results:
            max_end_ms = max(tr.end_ms for tr in transcript_results)
            recording.duration_seconds = max_end_ms // 1000

    # Set title from filename if not set
    if not recording.title:
        recording.title = filename.rsplit(".", 1)[0] if "." in filename else filename

    await db.flush()

    # Expire cached recording so selectinload refetches relationships
    db.expire(recording)

    # Reload to get the new segments
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id)
        .options(
            selectinload(Recording.segments),
            selectinload(Recording.summary),
            selectinload(Recording.action_items),
        )
    )
    recording = result.scalar_one_or_none()

    return _serialize_recording_detail(recording)
