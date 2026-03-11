"""Recording CRUD routes."""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select, text
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.deepgram import transcribe_audio_file
from app.core.embeddings import generate_embedding
from app.core.storage import get_storage_client
from app.core.summarizer import generate_title, resolve_highlight_timestamps, summarize_transcript
from app.models.highlight import Highlight
from app.models.recording import ActionItem, Folder, Recording, RecordingStatus, Segment, Summary

logger = logging.getLogger(__name__)
app_settings = get_settings()

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


class HighlightResponse(BaseModel):
    """Response for a recording highlight / key moment."""

    id: str
    recording_id: str
    category: str
    title: str
    description: str | None
    speaker: str | None
    start_ms: int | None
    end_ms: int | None
    importance: str


class SpeakerStatResponse(BaseModel):
    """Per-speaker statistics."""

    name: str
    total_duration_ms: int
    percentage: float
    segment_count: int
    avg_segment_duration_ms: int
    word_count: int
    words_per_minute: float
    first_spoke_ms: int
    last_spoke_ms: int


class TimelineEntry(BaseModel):
    """A single timeline entry."""

    speaker: str
    start_ms: int
    end_ms: int


class SpeakerStatsResponse(BaseModel):
    """Full speaker stats response."""

    recording_id: str
    total_duration_ms: int
    total_speakers: int
    speakers: list[SpeakerStatResponse]
    timeline: list[TimelineEntry]


class RelatedRecordingItem(BaseModel):
    """A single related recording result."""

    id: str
    title: str | None
    created_at: datetime
    recording_type: str
    similarity_score: float
    matching_topic: str | None


class RelatedRecordingsResponse(BaseModel):
    """Response containing related recordings."""

    recording_id: str
    related: list[RelatedRecordingItem]


class RecordingResponse(BaseModel):
    """Response for a recording."""

    id: str
    title: str | None
    type: str
    audio_url: str | None
    status: str
    failure_code: str | None
    failure_message: str | None
    uploaded_at: datetime | None
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
    highlights: list[HighlightResponse]


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


class TranscriptSegmentPayload(BaseModel):
    """Transcript segment payload from the native client."""

    text: str
    speaker: str | None = None
    start_ms: int = 0
    end_ms: int = 0
    confidence: float | None = None


class SaveTranscriptRequest(BaseModel):
    """Persist live transcript segments independent of audio upload."""

    segments: list[TranscriptSegmentPayload]
    duration_seconds: int | None = None


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


def _serialize_highlight(highlight: Highlight) -> HighlightResponse:
    return HighlightResponse(
        id=str(highlight.id),
        recording_id=str(highlight.recording_id),
        category=highlight.category,
        title=highlight.title,
        description=highlight.description,
        speaker=highlight.speaker,
        start_ms=highlight.start_ms,
        end_ms=highlight.end_ms,
        importance=highlight.importance,
    )


def _serialize_recording(recording: Recording) -> RecordingResponse:
    return RecordingResponse(
        id=str(recording.id),
        title=recording.title,
        type=recording.type,
        audio_url=recording.audio_url,
        status=recording.status,
        failure_code=recording.failure_code,
        failure_message=recording.failure_message,
        uploaded_at=recording.uploaded_at,
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
        highlights=[_serialize_highlight(h) for h in recording.highlights],
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


async def _load_recording_detail(
    recording_id: UUID,
    user_id: UUID,
    db: Database,
) -> Recording | None:
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user_id)
        .options(
            selectinload(Recording.segments),
            selectinload(Recording.summary),
            selectinload(Recording.action_items),
            selectinload(Recording.highlights),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def _mark_recording_failed(
    recording: Recording,
    db: Database,
    failure_code: str,
    failure_message: str,
) -> None:
    recording.status = RecordingStatus.FAILED.value
    recording.failure_code = failure_code
    recording.failure_message = failure_message
    await db.commit()


async def _mark_recording_failed_by_id(
    recording_id: UUID,
    db: Database,
    failure_code: str,
    failure_message: str,
) -> None:
    result = await db.execute(select(Recording).where(Recording.id == recording_id))
    recording = result.scalar_one_or_none()
    if recording is None:
        return
    await _mark_recording_failed(recording, db, failure_code, failure_message)


def _transcript_failure_details(error: HTTPException) -> tuple[str, str]:
    detail = str(error.detail) if error.detail is not None else "Failed to save transcript"
    normalized_detail = _normalize_failure_message(detail, "Failed to save transcript")
    is_empty_transcript = (
        error.status_code == status.HTTP_400_BAD_REQUEST
        and normalized_detail == "Transcript is empty"
    )
    if is_empty_transcript:
        return "transcript_empty", normalized_detail
    return "transcript_validation_failed", normalized_detail


async def _reset_recording_processing_state(recording_id: UUID, db: Database) -> None:
    """Replace transcript-derived data on re-upload instead of appending."""
    await db.execute(
        delete(ActionItem).where(
            ActionItem.recording_id == recording_id,
            ActionItem.source == "generated",
        )
    )
    await db.execute(delete(Highlight).where(Highlight.recording_id == recording_id))
    await db.execute(delete(Summary).where(Summary.recording_id == recording_id))
    await db.execute(delete(Segment).where(Segment.recording_id == recording_id))


def _measure_upload_size(file: UploadFile) -> int:
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    return size


def _upload_limit_message() -> str:
    return f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)}MB"


def _normalize_failure_message(error: Exception | str, fallback: str) -> str:
    message = str(error).strip()
    if not message:
        return fallback
    return message[:500]


def _extension_from_upload(file_name: str, content_type: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return ext

    for candidate_ext, candidate_content_type in EXTENSION_TO_CONTENT_TYPE.items():
        if candidate_content_type == content_type:
            return candidate_ext

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            f"Unsupported file type '.{ext}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}"
        ),
    )


async def _persist_client_segments(
    recording: Recording,
    db: Database,
    segments: list[TranscriptSegmentPayload],
    duration_seconds: int | None = None,
) -> str:
    normalized_segments = [segment for segment in segments if segment.text.strip()]
    if not normalized_segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is empty",
        )

    await _reset_recording_processing_state(recording.id, db)

    transcript_chunks: list[str] = []
    end_times: list[int] = []

    for segment in normalized_segments:
        text = segment.text.strip()
        embedding = None
        try:
            embedding = await generate_embedding(text)
        except Exception as error:
            logger.warning("Failed to generate embedding: %s", error)

        db.add(
            Segment(
                recording_id=recording.id,
                speaker=segment.speaker,
                content=text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                confidence=segment.confidence,
                embedding=embedding,
            )
        )
        transcript_chunks.append(text)
        end_times.append(segment.end_ms)

    if end_times:
        recording.duration_seconds = max(end_times) // 1000
    elif duration_seconds is not None:
        recording.duration_seconds = duration_seconds

    transcript_text = " ".join(transcript_chunks)
    if not recording.title and transcript_text:
        try:
            recording.title = await generate_title(transcript_text)
        except Exception as error:
            logger.warning("Title generation failed: %s", error)

    recording.status = RecordingStatus.READY.value
    recording.failure_code = None
    recording.failure_message = None
    await db.commit()
    return transcript_text


def _staging_directory_for_user(user_id: UUID) -> Path:
    return Path(app_settings.upload_staging_dir) / str(user_id)


def _staging_path(user_id: UUID, recording_id: UUID, ext: str) -> Path:
    return _staging_directory_for_user(user_id) / f"{recording_id}.{ext}"


def _delete_staged_file(path: str | None) -> None:
    if not path:
        return

    try:
        Path(path).unlink(missing_ok=True)
    except Exception as error:
        logger.warning("Failed to delete staged audio %s: %s", path, error)


async def _stage_upload_to_disk(
    *,
    file: UploadFile,
    user_id: UUID,
    recording_id: UUID,
    ext: str,
) -> tuple[Path, int]:
    """Persist the upload to the server staging volume before any external processing."""
    staging_dir = _staging_directory_for_user(user_id)
    staging_dir.mkdir(parents=True, exist_ok=True)

    final_path = _staging_path(user_id, recording_id, ext)
    temp_path = final_path.with_suffix(f".{ext}.part")
    total_size = 0

    try:
        with temp_path.open("wb") as staged_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break

                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=_upload_limit_message(),
                    )

                staged_file.write(chunk)

        temp_path.replace(final_path)
        return final_path, total_size
    except Exception:
        _delete_staged_file(str(temp_path))
        _delete_staged_file(str(final_path))
        raise
    finally:
        await file.close()


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
            selectinload(Recording.highlights),
        )
        .execution_options(populate_existing=True)
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    return _serialize_recording_detail(recording)


# ---- Export helpers ----


def _format_duration_mmss(seconds: int | None) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    if seconds is None or seconds < 0:
        return "0:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_timestamp_short(ms: int | None) -> str:
    """Format milliseconds as M:SS for markdown/txt."""
    if ms is None:
        return ""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    secs = total_seconds % 60
    return f"{minutes}:{secs:02d}"


def _format_timestamp_srt(ms: int | None) -> str:
    """Format milliseconds as HH:MM:SS,mmm for SRT."""
    if ms is None:
        return "00:00:00,000"
    hours = ms // 3_600_000
    remainder = ms % 3_600_000
    minutes = remainder // 60_000
    remainder = remainder % 60_000
    seconds = remainder // 1000
    millis = remainder % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _format_recording_date(created_at: datetime) -> str:
    """Format recording creation date for export headers."""
    return created_at.strftime("%B %d, %Y")


def _export_markdown(recording: Recording) -> str:
    """Export recording as Markdown."""
    lines: list[str] = []

    title = recording.title or "Untitled Recording"
    lines.append(f"# {title}")

    # Metadata line
    date_str = _format_recording_date(recording.created_at)
    duration_str = _format_duration_mmss(recording.duration_seconds)
    lines.append(f"*Date: {date_str} | Duration: {duration_str} | Type: {recording.type}*")
    lines.append("")

    # Summary section (only if present)
    if recording.summary and recording.summary.summary:
        lines.append("## Summary")
        lines.append(recording.summary.summary)
        lines.append("")

    # Key Highlights section (only if present)
    if recording.highlights:
        lines.append("## Key Highlights")
        for h in sorted(recording.highlights, key=lambda x: x.start_ms or 0):
            if h.speaker:
                ts = _format_timestamp_short(h.start_ms)
                speaker_part = f" ({h.speaker}, {ts})"
            elif h.start_ms is not None:
                speaker_part = f" ({_format_timestamp_short(h.start_ms)})"
            else:
                speaker_part = ""
            category = h.category.capitalize()
            lines.append(f"- **[{category}]** {h.title}{speaker_part}")
        lines.append("")

    # Transcript section
    lines.append("## Transcript")
    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)
    for seg in segments:
        speaker = seg.speaker or "Unknown"
        ts = _format_timestamp_short(seg.start_ms)
        ts_part = f" ({ts})" if ts else ""
        lines.append(f"**{speaker}**{ts_part}: {seg.content}")
    lines.append("")

    return "\n".join(lines)


def _export_txt(recording: Recording) -> str:
    """Export recording as plain text."""
    lines: list[str] = []

    title = recording.title or "Untitled Recording"
    lines.append(title)

    date_str = _format_recording_date(recording.created_at)
    duration_str = _format_duration_mmss(recording.duration_seconds)
    lines.append(f"Date: {date_str} | Duration: {duration_str}")
    lines.append("")

    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)
    for seg in segments:
        speaker = seg.speaker or "Unknown"
        ts = _format_timestamp_short(seg.start_ms)
        if ts:
            lines.append(f"[{speaker}, {ts}] {seg.content}")
        else:
            lines.append(f"[{speaker}] {seg.content}")
    lines.append("")

    return "\n".join(lines)


def _export_srt(recording: Recording) -> str:
    """Export recording as SRT subtitle format."""
    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)
    if not segments:
        return ""

    entries: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start_ts = _format_timestamp_srt(seg.start_ms)
        end_ts = _format_timestamp_srt(seg.end_ms)
        speaker = seg.speaker or "Unknown"
        entries.append(f"{i}")
        entries.append(f"{start_ts} --> {end_ts}")
        entries.append(f"[{speaker}] {seg.content}")
        entries.append("")

    return "\n".join(entries)


def _sanitize_filename(title: str | None) -> str:
    """Create a safe filename from a recording title."""
    name = title or "recording"
    # Remove characters unsafe for filenames
    safe = "".join(c if c.isalnum() or c in " -_" else "" for c in name)
    safe = safe.strip().replace(" ", "_")
    return safe[:100] or "recording"


@router.get("/{recording_id}/export")
async def export_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    format: Literal["markdown", "txt", "srt"] = Query(...),
) -> Response:
    """Export a recording transcript in the requested format."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(
            selectinload(Recording.segments),
            selectinload(Recording.summary),
            selectinload(Recording.highlights),
        )
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if format == "markdown":
        content = _export_markdown(recording)
        media_type = "text/markdown; charset=utf-8"
        ext = "md"
    elif format == "txt":
        content = _export_txt(recording)
        media_type = "text/plain; charset=utf-8"
        ext = "txt"
    else:
        content = _export_srt(recording)
        media_type = "text/srt; charset=utf-8"
        ext = "srt"

    filename = f"{_sanitize_filename(recording.title)}.{ext}"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        if recording.audio_url:
            try:
                await get_storage_client().delete_audio(recording.audio_url)
            except Exception as error:
                logger.warning("Failed to delete audio for recording %s: %s", recording.id, error)
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


@router.get("/{recording_id}/speaker-stats", response_model=SpeakerStatsResponse)
async def get_speaker_stats(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SpeakerStatsResponse:
    """Compute speaking statistics from transcript segments."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.segments))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)

    if not segments:
        return SpeakerStatsResponse(
            recording_id=str(recording.id),
            total_duration_ms=0,
            total_speakers=0,
            speakers=[],
            timeline=[],
        )

    # Group segments by speaker
    speaker_segments: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        name = seg.speaker or "Unknown"
        speaker_segments[name].append(seg)

    # Compute total duration from segment spans
    total_duration_ms = 0
    for seg in segments:
        start = seg.start_ms or 0
        end = seg.end_ms or 0
        total_duration_ms = max(total_duration_ms, end)

    # Build per-speaker stats
    speaker_stats: list[SpeakerStatResponse] = []
    for name, segs in speaker_segments.items():
        duration_ms = 0
        word_count = 0
        first_spoke_ms = None
        last_spoke_ms = None

        for seg in segs:
            start = seg.start_ms or 0
            end = seg.end_ms or 0
            duration_ms += max(0, end - start)
            word_count += len(seg.content.split())

            if first_spoke_ms is None or start < first_spoke_ms:
                first_spoke_ms = start
            if last_spoke_ms is None or start > last_spoke_ms:
                last_spoke_ms = start

        segment_count = len(segs)
        avg_duration = duration_ms // segment_count if segment_count > 0 else 0
        percentage = (duration_ms / total_duration_ms * 100) if total_duration_ms > 0 else 0.0
        duration_minutes = duration_ms / 60000
        wpm = word_count / duration_minutes if duration_minutes > 0 else 0.0

        speaker_stats.append(
            SpeakerStatResponse(
                name=name,
                total_duration_ms=duration_ms,
                percentage=round(percentage, 1),
                segment_count=segment_count,
                avg_segment_duration_ms=avg_duration,
                word_count=word_count,
                words_per_minute=round(wpm, 1),
                first_spoke_ms=first_spoke_ms or 0,
                last_spoke_ms=last_spoke_ms or 0,
            )
        )

    # Sort by duration descending, then name ascending for ties
    speaker_stats.sort(key=lambda s: (-s.total_duration_ms, s.name))

    # Build timeline from segments
    timeline = [
        TimelineEntry(
            speaker=seg.speaker or "Unknown",
            start_ms=seg.start_ms or 0,
            end_ms=seg.end_ms or 0,
        )
        for seg in segments
    ]

    return SpeakerStatsResponse(
        recording_id=str(recording.id),
        total_duration_ms=total_duration_ms,
        total_speakers=len(speaker_stats),
        speakers=speaker_stats,
        timeline=timeline,
    )


@router.get("/{recording_id}/related", response_model=RelatedRecordingsResponse)
async def get_related_recordings(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    limit: int = Query(5, ge=1, le=20),
) -> RelatedRecordingsResponse:
    """Find recordings with semantically similar content using pgvector cosine distance."""
    # Verify the recording exists and belongs to the user
    result = await db.execute(
        select(Recording).where(
            Recording.id == recording_id,
            Recording.user_id == user.id,
            Recording.deleted_at.is_(None),
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    # Get segments with embeddings for this recording to compute centroid
    centroid_query = text("""
        SELECT AVG(embedding)::vector AS centroid
        FROM segments
        WHERE recording_id = :recording_id
          AND embedding IS NOT NULL
    """)
    centroid_result = await db.execute(centroid_query, {"recording_id": str(recording_id)})
    centroid_row = centroid_result.fetchone()

    if centroid_row is None or centroid_row.centroid is None:
        return RelatedRecordingsResponse(
            recording_id=str(recording_id),
            related=[],
        )

    centroid_str = str(centroid_row.centroid)

    # Find segments from OTHER recordings closest to this centroid,
    # grouped by recording, with average similarity score.
    related_query = text("""
        WITH segment_similarities AS (
            SELECT
                s.recording_id,
                1 - (s.embedding <=> CAST(:centroid AS vector)) AS similarity
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
              AND s.recording_id != :source_recording_id
              AND s.embedding IS NOT NULL
        )
        SELECT
            r.id,
            r.title,
            r.created_at,
            r.type AS recording_type,
            AVG(ss.similarity) AS avg_similarity,
            MAX(ss.similarity) AS max_similarity
        FROM segment_similarities ss
        JOIN recordings r ON ss.recording_id = r.id
        GROUP BY r.id, r.title, r.created_at, r.type
        ORDER BY AVG(ss.similarity) DESC
        LIMIT :limit
    """)

    related_result = await db.execute(
        related_query,
        {
            "centroid": centroid_str,
            "user_id": str(user.id),
            "source_recording_id": str(recording_id),
            "limit": limit,
        },
    )
    related_rows = related_result.fetchall()

    # Fetch summaries for related recordings to extract matching topics
    topics_map: dict[str, str | None] = {}
    if related_rows:
        summary_result = await db.execute(
            select(Summary.recording_id, Summary.topics).where(
                Summary.recording_id.in_([row.id for row in related_rows])
            )
        )
        for srow in summary_result.fetchall():
            topics_list = srow.topics
            if topics_list and isinstance(topics_list, list) and len(topics_list) > 0:
                topics_map[str(srow.recording_id)] = topics_list[0]

    related_items = []
    for row in related_rows:
        rid = str(row.id)
        related_items.append(
            RelatedRecordingItem(
                id=rid,
                title=row.title,
                created_at=row.created_at,
                recording_type=row.recording_type,
                similarity_score=round(float(row.avg_similarity), 4),
                matching_topic=topics_map.get(rid),
            )
        )

    return RelatedRecordingsResponse(
        recording_id=str(recording_id),
        related=related_items,
    )


@router.post("/{recording_id}/transcript", response_model=RecordingDetailResponse)
async def save_transcript(
    recording_id: UUID,
    request: SaveTranscriptRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingDetailResponse:
    """Persist a live transcript without storing live-capture audio on the server."""
    user_id = user.id
    recording = await _load_recording_detail(recording_id, user_id, db)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    try:
        await _persist_client_segments(
            recording,
            db,
            request.segments,
            duration_seconds=request.duration_seconds,
        )
    except HTTPException as error:
        await db.rollback()
        try:
            failure_code, failure_message = _transcript_failure_details(error)
            await _mark_recording_failed_by_id(
                recording_id,
                db,
                failure_code,
                failure_message,
            )
        except Exception:
            logger.exception(
                "Failed to mark recording %s as failed after transcript validation error",
                recording_id,
            )
        raise
    except Exception as error:
        logger.exception("Failed to save transcript for recording %s", recording_id)
        await db.rollback()
        try:
            await _mark_recording_failed_by_id(
                recording_id,
                db,
                "transcript_save_failed",
                _normalize_failure_message(error, "Failed to save transcript"),
            )
        except Exception:
            logger.exception(
                "Failed to mark recording %s as failed after transcript save error",
                recording_id,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save transcript",
        ) from error

    db.expire_all()
    refreshed = await _load_recording_detail(recording_id, user_id, db)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    return _serialize_recording_detail(refreshed)


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

    # Replace highlights on regeneration.
    await db.execute(
        delete(Highlight).where(Highlight.recording_id == recording.id)
    )

    # Resolve highlight timestamps from segments and persist.
    raw_highlights = summary_result.highlights or []
    if raw_highlights:
        segment_dicts = [
            {
                "content": seg.content,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
            }
            for seg in sorted(recording.segments, key=lambda x: x.start_ms or 0)
        ]
        resolved = resolve_highlight_timestamps(raw_highlights, segment_dicts)
        for hl in resolved:
            category = str(hl.get("category", "insight")).strip()[:30]
            title = str(hl.get("title", "")).strip()
            if not title:
                continue
            importance = hl.get("importance", "medium")
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            db.add(
                Highlight(
                    recording_id=recording.id,
                    category=category,
                    title=title[:500],
                    description=hl.get("description"),
                    speaker=hl.get("speaker"),
                    start_ms=hl.get("start_ms"),
                    end_ms=hl.get("end_ms"),
                    importance=importance,
                )
            )

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
MAX_UPLOAD_SIZE = app_settings.upload_max_bytes


@router.post("/{recording_id}/upload", response_model=RecordingDetailResponse)
async def upload_audio_file(
    recording_id: UUID,
    file: UploadFile,
    user: CurrentUser,
    db: Database,
) -> RecordingDetailResponse:
    """Upload an imported audio file to an existing recording."""
    # Validate recording exists and belongs to user
    user_id = user.id
    recording = await _load_recording_detail(recording_id, user_id, db)
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

    upload_size = _measure_upload_size(file)
    if upload_size > MAX_UPLOAD_SIZE:
        detail = _upload_limit_message()
        await _mark_recording_failed(recording, db, "file_too_large", detail)
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=detail)

    content_type = EXTENSION_TO_CONTENT_TYPE.get(ext, "application/octet-stream")

    storage = get_storage_client()
    old_audio_url = recording.audio_url

    try:
        staged_path, _ = await _stage_upload_to_disk(
            file=file,
            user_id=user_id,
            recording_id=recording_id,
            ext=ext,
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            await _mark_recording_failed(recording, db, "file_too_large", str(exc.detail))
            raise
        logger.exception("Failed to stage audio for recording %s", recording_id)
        detail = "Failed to save recording for upload"
        await _mark_recording_failed(
            recording,
            db,
            "staging_failed",
            _normalize_failure_message(exc, detail),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc

    recording.status = RecordingStatus.UPLOADING.value
    recording.failure_code = None
    recording.failure_message = None
    await db.commit()

    try:
        with staged_path.open("rb") as staged_file:
            s3_key = await storage.upload_audio_fileobj(
                staged_file,
                user_id,
                recording_id,
                content_type,
            )
    except Exception as exc:
        logger.exception("Failed to store audio for recording %s", recording_id)
        _delete_staged_file(str(staged_path))
        detail = "Failed to store imported audio"
        await _mark_recording_failed(
            recording,
            db,
            "storage_upload_failed",
            _normalize_failure_message(exc, detail),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc

    recording.audio_url = s3_key
    recording.status = RecordingStatus.PROCESSING.value
    recording.failure_code = None
    recording.failure_message = None
    recording.uploaded_at = datetime.now(timezone.utc)
    recording.duration_seconds = None

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await storage.delete_audio(s3_key)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up orphaned S3 audio %s for recording %s: %s",
                s3_key,
                recording_id,
                cleanup_error,
            )
        raise

    if old_audio_url and old_audio_url != s3_key:
        try:
            await storage.delete_audio(old_audio_url)
        except Exception as exc:
            logger.warning("Failed to delete superseded audio %s: %s", old_audio_url, exc)

    transcript_results = []
    transcript_text = ""

    try:
        await _reset_recording_processing_state(recording_id, db)

        with staged_path.open("rb") as staged_file:
            transcript_results = await transcribe_audio_file(
                staged_file.read(),
                language=recording.language or "en",
                content_type=content_type,
            )

        for tr in transcript_results:
            embedding = None
            if tr.text.strip():
                try:
                    embedding = await generate_embedding(tr.text)
                except Exception as exc:
                    logger.warning("Failed to generate embedding: %s", exc)

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
            transcript_text = " ".join(tr.text for tr in transcript_results if tr.text.strip())

        if not recording.title and transcript_text.strip():
            try:
                recording.title = await generate_title(transcript_text)
            except Exception as exc:
                logger.warning("Title generation failed: %s", exc)
                recording.title = None

        recording.status = RecordingStatus.READY.value
        recording.failure_code = None
        recording.failure_message = None
        await db.commit()
        _delete_staged_file(str(staged_path))
    except Exception as exc:
        logger.exception("Recording processing failed for %s", recording_id)
        await db.rollback()

        recording = await _load_recording_detail(recording_id, user_id, db)
        if recording is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Recording disappeared after upload",
            ) from exc

        recording.status = RecordingStatus.FAILED.value
        recording.failure_code = "processing_failed"
        recording.failure_message = _normalize_failure_message(
            exc,
            "Audio saved, but processing failed",
        )
        await db.commit()
        _delete_staged_file(str(staged_path))

    db.expire_all()
    recording = await _load_recording_detail(recording_id, user_id, db)
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Recording disappeared after upload",
        )

    return _serialize_recording_detail(recording)
