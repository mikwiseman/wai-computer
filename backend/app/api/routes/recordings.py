"""Recording CRUD routes."""

import logging
import re
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Database
from app.billing.quota import record_recording_transcript_words
from app.config import get_settings
from app.core.embeddings import generate_embedding
from app.core.error_sanitizer import sanitize_failure_message
from app.core.observability import (
    add_sentry_breadcrumb,
    bind_recording_context,
    capture_sentry_message,
    safe_filename_metadata,
    safe_text_digest,
)
from app.core.personalization import summary_personalization_instructions
from app.core.recording_audio_processing import (
    apply_no_speech_failure,
    delete_staged_file,
    is_no_speech_placeholder,
    reset_recording_processing_state,
)
from app.core.summarizer import (
    generate_title,
    summarize_transcript,
)
from app.core.summarizer import (
    resolve_highlight_timestamps as _resolve_highlight_timestamps,
)
from app.core.summary_generation import (
    apply_summary_result,
    build_summary_transcript,
    combine_summary_instructions,
    latest_summary_generation_job,
    load_active_summary_generation_job,
    resolve_summary_language_preference,
    resolve_summary_style_preference,
    summary_transcript_hash,
)
from app.core.voice_identification import (
    rematch_recording_speakers,
    store_voiceprint_from_recording_speaker,
)
from app.models.highlight import Highlight
from app.models.person import Person
from app.models.recording import (
    ActionItem,
    Folder,
    Recording,
    RecordingShare,
    RecordingStatus,
    Segment,
    Summary,
    SummaryGenerationJob,
    SummaryGenerationStatus,
)

logger = logging.getLogger(__name__)
app_settings = get_settings()

router = APIRouter(prefix="/recordings", tags=["recordings"])

# Kept as a route-level patch point for older tests and integrations that
# exercised summary highlight timestamping before durable summary generation
# moved the persistence logic into app.core.summary_generation.
resolve_highlight_timestamps = _resolve_highlight_timestamps


class SegmentResponse(BaseModel):
    """Response for a transcript segment."""

    id: str
    speaker: str | None
    raw_label: str | None
    person_id: str | None
    display_name: str | None
    auto_assigned: bool
    match_confidence: float | None
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


class SummaryGenerationResponse(BaseModel):
    """Durable state for a recording summary generation request."""

    job_id: str | None
    recording_id: str
    status: str
    stage: str
    progress_percent: int
    message: str
    requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_message: str | None


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


class TopicCount(BaseModel):
    """A topic with its occurrence count."""

    topic: str
    count: int


class PersonCount(BaseModel):
    """A person with their mention count."""

    name: str
    count: int


class DigestActionItem(BaseModel):
    """Action item in digest context."""

    id: str
    recording_id: str
    recording_title: str | None
    task: str
    owner: str | None
    priority: str | None
    status: str


class DigestHighlight(BaseModel):
    """Highlight in digest context."""

    id: str
    recording_id: str
    recording_title: str | None
    category: str
    title: str
    importance: str


class DailyBreakdown(BaseModel):
    """Per-day recording counts and duration."""

    date: str
    count: int
    duration_seconds: int


class WeeklyDigestResponse(BaseModel):
    """Aggregated weekly digest of recordings."""

    period_start: str
    period_end: str
    total_recordings: int
    total_duration_seconds: int
    recordings_by_type: dict[str, int]
    top_topics: list[TopicCount]
    top_people: list[PersonCount]
    pending_action_items: list[DigestActionItem]
    highlights: list[DigestHighlight]
    sentiment_breakdown: dict[str, int]
    daily_breakdown: list[DailyBreakdown]


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
    starred_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RecordingDetailResponse(RecordingResponse):
    """Detailed response for a recording including segments and summary."""

    segments: list[SegmentResponse]
    summary: SummaryResponse | None
    summary_generation: SummaryGenerationResponse
    action_items: list[ActionItemResponse]
    highlights: list[HighlightResponse]


class RecordingShareLinkResponse(BaseModel):
    """Response returned when an owner creates a public share link."""

    recording_id: str
    token: str
    url: str
    created_at: datetime


class SharedRecordingResponse(BaseModel):
    """Public, read-only recording payload exposed by a share token."""

    id: str
    title: str | None
    type: str
    duration_seconds: int | None
    language: str | None
    created_at: datetime
    shared_at: datetime
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


class StartSummaryGenerationRequest(BaseModel):
    """Optional one-off instructions for a manual summary generation run."""

    instructions: str | None = Field(default=None, max_length=4000)

    @field_validator("instructions", mode="before")
    @classmethod
    def normalize_instructions(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class WeekCount(BaseModel):
    """Recording count for a single week."""

    week: str
    count: int


class AnalyticsResponse(BaseModel):
    """Aggregate recording statistics."""

    total_recordings: int
    total_duration_seconds: int
    average_duration_seconds: int
    total_words: int
    by_type: dict[str, int]
    by_week: list[WeekCount]


class TranscriptSearchMatch(BaseModel):
    """A single segment matching a transcript search query."""

    segment_id: str
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None
    match_count: int


class TranscriptSearchResponse(BaseModel):
    """Response from transcript search within a recording."""

    recording_id: str
    query: str
    total_matches: int
    segments: list[TranscriptSearchMatch]


class BulkOperationRequest(BaseModel):
    """Request for bulk operations on recordings."""

    recording_ids: list[str] = Field(min_length=1)
    action: Literal["delete", "restore", "move"]
    folder_id: str | None = None

    @field_validator("recording_ids")
    @classmethod
    def validate_recording_ids(cls, value: list[str]) -> list[str]:
        for rid in value:
            try:
                UUID(rid)
            except ValueError as exc:
                raise ValueError(f"Invalid UUID: {rid}") from exc
        return value

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                UUID(value)
            except ValueError as exc:
                raise ValueError(f"Invalid UUID: {value}") from exc
        return value


class BulkOperationResponse(BaseModel):
    """Response from a bulk operation."""

    processed: int
    failed: int


class KeywordItem(BaseModel):
    """A single keyword/term with its frequency."""

    term: str
    count: int


class KeywordsResponse(BaseModel):
    """Response from keyword extraction."""

    recording_id: str
    total_words: int
    keywords: list[KeywordItem]


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


def _serialize_summary(
    summary: Summary | None, names: dict[str, str] | None = None
) -> SummaryResponse | None:
    if summary is None:
        return None

    names = names or {}
    return SummaryResponse(
        summary=_apply_speaker_names(summary.summary, names),
        key_points=(
            [_apply_speaker_names(point, names) for point in summary.key_points]
            if summary.key_points
            else summary.key_points
        ),
        decisions=summary.decisions,
        topics=summary.topics,
        people_mentioned=summary.people_mentioned,
        sentiment=summary.sentiment,
    )


def _summary_generation_message(status_value: str, stage: str) -> str:
    if status_value == "not_started":
        return "Summary has not been generated."
    if status_value == SummaryGenerationStatus.QUEUED.value:
        return "Summary generation is queued."
    if status_value == SummaryGenerationStatus.RUNNING.value:
        if stage == "preparing_transcript":
            return "Preparing transcript for summary generation."
        if stage == "saving_summary":
            return "Saving generated summary."
        return "Generating summary."
    if status_value == SummaryGenerationStatus.SUCCEEDED.value:
        return "Summary is ready."
    if status_value == SummaryGenerationStatus.FAILED.value:
        return "Summary generation failed."
    return "Summary generation status is unknown."


def _serialize_summary_generation(
    *,
    recording_id: UUID,
    summary: Summary | None,
    job: SummaryGenerationJob | None,
) -> SummaryGenerationResponse:
    if job is None:
        status_value = "succeeded" if summary is not None else "not_started"
        progress = 100 if summary is not None else 0
        stage = "complete" if summary is not None else "idle"
        return SummaryGenerationResponse(
            job_id=None,
            recording_id=str(recording_id),
            status=status_value,
            stage=stage,
            progress_percent=progress,
            message=_summary_generation_message(status_value, stage),
            requested_at=None,
            started_at=None,
            completed_at=None,
            failed_at=None,
            error_code=None,
            error_message=None,
        )

    return SummaryGenerationResponse(
        job_id=str(job.id),
        recording_id=str(job.recording_id),
        status=job.status,
        stage=job.stage,
        progress_percent=job.progress_percent,
        message=_summary_generation_message(job.status, job.stage),
        requested_at=job.requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        failed_at=job.failed_at,
        error_code=job.error_code,
        error_message=job.error_message,
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


def _serialize_highlight(
    highlight: Highlight, names: dict[str, str] | None = None
) -> HighlightResponse:
    speaker = highlight.speaker
    if speaker and names and speaker in names:
        speaker = names[speaker]
    return HighlightResponse(
        id=str(highlight.id),
        recording_id=str(highlight.recording_id),
        category=highlight.category,
        title=_apply_speaker_names(highlight.title, names or {}),
        description=_apply_speaker_names(highlight.description, names or {}),
        speaker=speaker,
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
        starred_at=recording.starred_at,
        created_at=recording.created_at,
        updated_at=recording.updated_at,
    )


def _serialize_segment(segment: Segment) -> SegmentResponse:
    display_name = segment.person.display_name if segment.person is not None else None
    return SegmentResponse(
        id=str(segment.id),
        speaker=segment.speaker,
        raw_label=segment.raw_label,
        person_id=str(segment.person_id) if segment.person_id is not None else None,
        display_name=display_name,
        auto_assigned=segment.auto_assigned,
        match_confidence=segment.match_confidence,
        content=segment.content,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        confidence=segment.confidence,
    )


def _serialize_recording_detail(recording: Recording) -> RecordingDetailResponse:
    names = _assigned_speaker_names(recording)
    return RecordingDetailResponse(
        **_serialize_recording(recording).model_dump(),
        segments=[
            _serialize_segment(s)
            for s in sorted(recording.segments, key=lambda x: x.start_ms or 0)
        ],
        summary=_serialize_summary(recording.summary, names),
        summary_generation=_serialize_summary_generation(
            recording_id=recording.id,
            summary=recording.summary,
            job=latest_summary_generation_job(recording),
        ),
        action_items=[_serialize_action_item(a) for a in recording.action_items],
        highlights=[_serialize_highlight(h, names) for h in recording.highlights],
    )


def _recording_detail_load_options():
    """Eager-load every relationship used by detail serialization."""
    return (
        selectinload(Recording.segments).selectinload(Segment.person),
        selectinload(Recording.summary),
        selectinload(Recording.summary_generation_jobs),
        selectinload(Recording.action_items),
        selectinload(Recording.highlights),
    )


def _share_token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _shared_recording_url(token: str) -> str:
    return f"{app_settings.frontend_url.rstrip('/')}/share/{token}"


async def _generate_unique_share_token(db: Database) -> tuple[str, str]:
    for _ in range(5):
        token = secrets.token_urlsafe(32)
        token_hash = _share_token_hash(token)
        existing_result = await db.execute(
            select(RecordingShare.id).where(RecordingShare.token_hash == token_hash)
        )
        if existing_result.scalar_one_or_none() is None:
            return token, token_hash

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Unable to create a share link. Please try again.",
    )


def _serialize_shared_recording(
    recording: Recording,
    share: RecordingShare,
) -> SharedRecordingResponse:
    return SharedRecordingResponse(
        id=str(recording.id),
        title=recording.title,
        type=recording.type,
        duration_seconds=recording.duration_seconds,
        language=recording.language,
        created_at=recording.created_at,
        shared_at=share.created_at,
        segments=[
            _serialize_segment(s)
            for s in sorted(recording.segments, key=lambda x: x.start_ms or 0)
        ],
        summary=_serialize_summary(recording.summary, _assigned_speaker_names(recording)),
        action_items=[_serialize_action_item(a) for a in recording.action_items],
        highlights=[
            _serialize_highlight(h, _assigned_speaker_names(recording))
            for h in recording.highlights
        ],
    )


async def _load_active_share(token: str, db: Database) -> RecordingShare:
    if len(token) < 20 or len(token) > 256:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared note not found")

    result = await db.execute(
        select(RecordingShare)
        .where(
            RecordingShare.token_hash == _share_token_hash(token),
            RecordingShare.revoked_at.is_(None),
        )
        .options(
            selectinload(RecordingShare.recording)
            .selectinload(Recording.segments)
            .selectinload(Segment.person),
            selectinload(RecordingShare.recording).selectinload(Recording.summary),
            selectinload(RecordingShare.recording).selectinload(Recording.action_items),
            selectinload(RecordingShare.recording).selectinload(Recording.highlights),
        )
    )
    share = result.scalar_one_or_none()

    if share is None or share.recording.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared note not found")

    return share


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
    *,
    include_deleted: bool = True,
) -> Recording | None:
    query = (
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user_id)
        .options(*_recording_detail_load_options())
        .execution_options(populate_existing=True)
    )
    if not include_deleted:
        query = query.where(Recording.deleted_at.is_(None))

    result = await db.execute(
        query
    )
    return result.scalar_one_or_none()


async def _load_active_recording(
    recording_id: UUID,
    user_id: UUID,
    db: Database,
) -> Recording | None:
    result = await db.execute(
        select(Recording).where(
            Recording.id == recording_id,
            Recording.user_id == user_id,
            Recording.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


def _has_canonical_audio_processing(recording: Recording) -> bool:
    """Return true when uploaded audio owns canonical transcript generation."""
    if recording.status in {
        RecordingStatus.UPLOADING.value,
        RecordingStatus.PROCESSING.value,
    }:
        return True
    return recording.uploaded_at is not None and recording.status in {
        RecordingStatus.READY.value,
        RecordingStatus.FAILED.value,
    }


async def _claim_audio_upload(
    recording_id: UUID,
    user_id: UUID,
    db: Database,
) -> bool:
    result = await db.execute(
        update(Recording)
        .where(
            Recording.id == recording_id,
            Recording.user_id == user_id,
            Recording.deleted_at.is_(None),
            Recording.status.notin_(
                [
                    RecordingStatus.UPLOADING.value,
                    RecordingStatus.PROCESSING.value,
                ]
            ),
            ~(
                (Recording.uploaded_at.is_not(None))
                & (Recording.status.in_(
                    [
                        RecordingStatus.READY.value,
                        RecordingStatus.FAILED.value,
                    ]
                ))
            ),
        )
        .values(
            status=RecordingStatus.UPLOADING.value,
            failure_code=None,
            failure_message=None,
            uploaded_at=datetime.now(timezone.utc),
            audio_url=None,
            duration_seconds=None,
        )
    )
    await db.commit()
    return result.rowcount == 1


async def _mark_recording_failed(
    recording: Recording,
    db: Database,
    failure_code: str,
    failure_message: str,
) -> None:
    recording.status = RecordingStatus.FAILED.value
    recording.failure_code = failure_code
    recording.failure_message = sanitize_failure_message(failure_message)
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
    return "transcript_validation_failed", normalized_detail


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
    fallback_language: str | None = None,
) -> str:
    nonempty_segments = [segment for segment in segments if segment.text.strip()]
    normalized_segments = [
        segment
        for segment in nonempty_segments
        if not is_no_speech_placeholder(segment.text)
    ]
    if not normalized_segments:
        if duration_seconds is not None:
            recording.duration_seconds = duration_seconds
        elif nonempty_segments:
            recording.duration_seconds = (
                max(segment.end_ms for segment in nonempty_segments) // 1000
            )
        if recording.segments:
            recording.status = RecordingStatus.READY.value
            recording.failure_code = None
            recording.failure_message = None
        else:
            apply_no_speech_failure(recording, fallback_language)
        await db.commit()
        return ""

    await reset_recording_processing_state(recording.id, db)

    transcript_chunks: list[str] = []
    end_times: list[int] = []

    for segment in normalized_segments:
        text = segment.text.strip()
        embedding = None
        try:
            embedding = await generate_embedding(
                text,
                usage_user_id=recording.user_id,
                usage_recording_id=recording.id,
                usage_feature="recording",
                usage_operation="embedding.segment",
            )
        except Exception as error:
            logger.warning("Failed to generate embedding: %s", error)

        db.add(
            Segment(
                recording_id=recording.id,
                speaker=segment.speaker,
                raw_label=segment.speaker,
                content=text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                confidence=segment.confidence,
                embedding=embedding,
            )
        )
        transcript_chunks.append(text)
        end_times.append(segment.end_ms)

    segment_duration_seconds = max(end_times) // 1000 if end_times else None
    if duration_seconds is not None and segment_duration_seconds is not None:
        recording.duration_seconds = max(duration_seconds, segment_duration_seconds)
    elif duration_seconds is not None:
        recording.duration_seconds = duration_seconds
    elif segment_duration_seconds is not None:
        recording.duration_seconds = segment_duration_seconds

    transcript_text = " ".join(transcript_chunks)
    if not recording.title and transcript_text:
        try:
            recording.title = await generate_title(
                transcript_text,
                language=recording.language or "auto",
                usage_user_id=recording.user_id,
                usage_recording_id=recording.id,
            )
        except Exception as error:
            logger.warning("Title generation failed: %s", error)

    recording.status = RecordingStatus.READY.value
    recording.failure_code = None
    recording.failure_message = None
    await record_recording_transcript_words(db, recording, transcript_text)
    await db.commit()
    return transcript_text


def _staging_directory_for_user(user_id: UUID) -> Path:
    return Path(app_settings.upload_staging_dir) / str(user_id)


def _staging_path(user_id: UUID, recording_id: UUID, ext: str) -> Path:
    return _staging_directory_for_user(user_id) / f"{recording_id}.{ext}"


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
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=_upload_limit_message(),
                    )

                staged_file.write(chunk)

        temp_path.replace(final_path)
        return final_path, total_size
    except Exception:
        delete_staged_file(temp_path)
        delete_staged_file(final_path)
        raise
    finally:
        await file.close()


async def enqueue_recording_audio_processing(
    *,
    recording_id: UUID,
    user_id: UUID,
    staged_path: Path,
    content_type: str,
    user_default_language: str | None,
    client_duration_seconds: int | None = None,
    client_file_size_bytes: int | None = None,
    staged_size_bytes: int | None = None,
) -> None:
    from app.tasks.celery_app import celery_app

    celery_app.send_task(
        "app.tasks.recording_audio_processing.process_staged_recording_upload",
        kwargs={
            "recording_id": str(recording_id),
            "user_id": str(user_id),
            "staged_path": str(staged_path),
            "content_type": content_type,
            "user_default_language": user_default_language,
            "client_duration_seconds": client_duration_seconds,
            "client_file_size_bytes": client_file_size_bytes,
            "staged_size_bytes": staged_size_bytes,
        },
    )


def enqueue_summary_generation(job_id: UUID) -> str:
    from app.tasks.celery_app import celery_app

    result = celery_app.send_task(
        "app.tasks.summary_generation.generate_recording_summary",
        kwargs={"job_id": str(job_id)},
    )
    return str(result.id)


@router.get("", response_model=list[RecordingResponse])
async def list_recordings(
    user: CurrentUser,
    db: Database,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    type: Literal["meeting", "note", "reflection"] | None = None,
    folder_id: UUID | None = None,
    trashed: bool = False,
    starred: bool = False,
    updated_after: datetime | None = None,
) -> list[RecordingResponse]:
    """List user's recordings.

    ``updated_after`` filters to recordings updated strictly after the given
    timestamp (ascending order) for watermark-based incremental sync.
    """
    query = select(Recording).where(Recording.user_id == user.id)

    if trashed:
        query = query.where(Recording.deleted_at.is_not(None))
    else:
        query = query.where(Recording.deleted_at.is_(None))

    if type:
        query = query.where(Recording.type == type)
    if folder_id is not None:
        query = query.where(Recording.folder_id == folder_id)
    if starred:
        query = query.where(Recording.starred_at.is_not(None))
    if updated_after is not None:
        query = query.where(Recording.updated_at > updated_after)

    if updated_after is not None:
        # Stable forward pagination for watermark-based incremental sync.
        query = query.order_by(Recording.updated_at.asc(), Recording.id.asc())
    else:
        query = query.order_by(Recording.created_at.desc())
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    recordings = result.scalars().all()

    return [_serialize_recording(recording) for recording in recordings]


@router.get("/digest/weekly", response_model=WeeklyDigestResponse)
async def get_weekly_digest(
    user: CurrentUser,
    db: Database,
) -> WeeklyDigestResponse:
    """Return an aggregated digest of the user's recordings from the past 7 days."""
    now = datetime.now(timezone.utc)
    period_end = now
    period_start = now - timedelta(days=7)

    # Fetch all non-deleted recordings from the last 7 days with related data
    result = await db.execute(
        select(Recording)
        .where(
            Recording.user_id == user.id,
            Recording.deleted_at.is_(None),
            Recording.created_at >= period_start,
        )
        .options(
            selectinload(Recording.summary),
            selectinload(Recording.action_items),
            selectinload(Recording.highlights),
        )
        .order_by(Recording.created_at.asc())
    )
    recordings = list(result.scalars().all())

    # Totals
    total_recordings = len(recordings)
    total_duration = sum(r.duration_seconds or 0 for r in recordings)

    # Type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    for r in recordings:
        type_counts[r.type] += 1

    # Topic aggregation from summaries
    topic_counter: dict[str, int] = defaultdict(int)
    people_counter: dict[str, int] = defaultdict(int)
    sentiment_counter: dict[str, int] = defaultdict(int)

    for r in recordings:
        if r.summary:
            if r.summary.topics:
                for topic in r.summary.topics:
                    topic_counter[topic] += 1
            if r.summary.people_mentioned:
                for person in r.summary.people_mentioned:
                    people_counter[person] += 1
            if r.summary.sentiment:
                sentiment_counter[r.summary.sentiment] += 1

    top_topics = [
        TopicCount(topic=t, count=c)
        for t, c in sorted(topic_counter.items(), key=lambda x: -x[1])[:10]
    ]
    top_people = [
        PersonCount(name=p, count=c)
        for p, c in sorted(people_counter.items(), key=lambda x: -x[1])[:10]
    ]

    # Pending action items
    pending_items: list[DigestActionItem] = []
    for r in recordings:
        for ai in r.action_items:
            if ai.status == "pending":
                pending_items.append(
                    DigestActionItem(
                        id=str(ai.id),
                        recording_id=str(r.id),
                        recording_title=r.title,
                        task=ai.task,
                        owner=ai.owner,
                        priority=ai.priority,
                        status=ai.status,
                    )
                )

    # Highlights (top ones by importance)
    all_highlights: list[tuple[Highlight, Recording]] = []
    for r in recordings:
        for h in r.highlights:
            all_highlights.append((h, r))

    # Sort: high > medium > low
    importance_order = {"high": 0, "medium": 1, "low": 2}
    all_highlights.sort(key=lambda x: importance_order.get(x[0].importance, 1))

    digest_highlights = [
        DigestHighlight(
            id=str(h.id),
            recording_id=str(r.id),
            recording_title=r.title,
            category=h.category,
            title=h.title,
            importance=h.importance,
        )
        for h, r in all_highlights[:15]
    ]

    # Daily breakdown for the 7-day period (ending today)
    daily: dict[str, dict] = {}
    today = period_end.date()
    for day_offset in range(7):
        day = today - timedelta(days=6 - day_offset)
        daily[day.isoformat()] = {"count": 0, "duration_seconds": 0}

    for r in recordings:
        day_key = r.created_at.date().isoformat()
        if day_key in daily:
            daily[day_key]["count"] += 1
            daily[day_key]["duration_seconds"] += r.duration_seconds or 0

    daily_breakdown = [
        DailyBreakdown(date=d, count=v["count"], duration_seconds=v["duration_seconds"])
        for d, v in sorted(daily.items())
    ]

    return WeeklyDigestResponse(
        period_start=period_start.date().isoformat(),
        period_end=period_end.date().isoformat(),
        total_recordings=total_recordings,
        total_duration_seconds=total_duration,
        recordings_by_type=dict(type_counts),
        top_topics=top_topics,
        top_people=top_people,
        pending_action_items=pending_items,
        highlights=digest_highlights,
        sentiment_breakdown=dict(sentiment_counter),
        daily_breakdown=daily_breakdown,
    )


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_recording_analytics(
    user: CurrentUser,
    db: Database,
) -> AnalyticsResponse:
    """Return aggregate statistics about the user's recordings."""
    result = await db.execute(
        select(Recording)
        .where(
            Recording.user_id == user.id,
            Recording.deleted_at.is_(None),
        )
        .options(selectinload(Recording.segments))
    )
    recordings = list(result.scalars().all())

    total_recordings = len(recordings)
    total_duration = sum(r.duration_seconds or 0 for r in recordings)
    avg_duration = total_duration // total_recordings if total_recordings > 0 else 0

    # Count words across all segments
    total_words = 0
    for r in recordings:
        for s in r.segments:
            total_words += len(s.content.split())

    # Type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    for r in recordings:
        type_counts[r.type] += 1

    # Weekly breakdown
    week_counts: dict[str, int] = defaultdict(int)
    for r in recordings:
        # ISO year-week format
        iso_year, iso_week, _ = r.created_at.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        week_counts[week_key] += 1

    by_week = [
        WeekCount(week=w, count=c)
        for w, c in sorted(week_counts.items())
    ]

    return AnalyticsResponse(
        total_recordings=total_recordings,
        total_duration_seconds=total_duration,
        average_duration_seconds=avg_duration,
        total_words=total_words,
        by_type=dict(type_counts),
        by_week=by_week,
    )


@router.post("/bulk", response_model=BulkOperationResponse)
async def bulk_recording_operation(
    request: BulkOperationRequest,
    user: CurrentUser,
    db: Database,
) -> BulkOperationResponse:
    """Perform a bulk operation on multiple recordings."""
    recording_uuids = [UUID(rid) for rid in request.recording_ids]

    # Validate folder if move action
    if request.action == "move" and request.folder_id is not None:
        folder = await _require_folder(UUID(request.folder_id), user.id, db)
        folder_id = folder.id if folder else None
    elif request.action == "move":
        folder_id = None
    else:
        folder_id = None

    # Fetch all recordings owned by the user
    result = await db.execute(
        select(Recording).where(
            Recording.id.in_(recording_uuids),
            Recording.user_id == user.id,
        )
    )
    found_recordings = {r.id: r for r in result.scalars().all()}

    processed = 0
    for rid in recording_uuids:
        recording = found_recordings.get(rid)
        if recording is None:
            continue

        if request.action == "delete":
            recording.deleted_at = datetime.now(timezone.utc)
        elif request.action == "restore":
            recording.deleted_at = None
        elif request.action == "move":
            recording.folder_id = folder_id

        processed += 1

    await db.flush()

    return BulkOperationResponse(
        processed=processed,
        failed=len(recording_uuids) - processed,
    )


@router.post("", response_model=RecordingResponse, status_code=status.HTTP_201_CREATED)
async def create_recording(
    request: CreateRecordingRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """Create a new recording."""
    add_sentry_breadcrumb(
        category="recording",
        message="Creating recording",
        data={"type": request.type},
    )
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
    bind_recording_context(str(recording.id))
    logger.info("recording created type=%s language=%s", request.type, language)

    return _serialize_recording(recording)


@router.post(
    "/{recording_id}/share",
    response_model=RecordingShareLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recording_share_link(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> RecordingShareLinkResponse:
    """Create a public, read-only share link for an active recording."""
    recording = await _load_active_recording(recording_id, user.id, db)

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    token, token_hash = await _generate_unique_share_token(db)
    share = RecordingShare(recording_id=recording.id, token_hash=token_hash)
    db.add(share)
    await db.flush()

    add_sentry_breadcrumb(
        category="recording",
        message="Created recording share link",
        data={"recording_id": str(recording.id)},
    )

    return RecordingShareLinkResponse(
        recording_id=str(recording.id),
        token=token,
        url=_shared_recording_url(token),
        created_at=share.created_at,
    )


@router.get("/shared/{token}", response_model=SharedRecordingResponse)
async def get_shared_recording(
    token: str,
    db: Database,
) -> SharedRecordingResponse:
    """Open a public, read-only recording by share token."""
    share = await _load_active_share(token, db)
    return _serialize_shared_recording(share.recording, share)


@router.get("/shared/{token}/export")
async def export_shared_recording(
    token: str,
    db: Database,
    format: Literal["markdown"] = Query("markdown"),
    locale: Literal["en", "ru"] | None = Query(None),
) -> Response:
    """Export a public shared recording as Markdown without requiring auth."""
    share = await _load_active_share(token, db)

    content = _export_markdown(share.recording, locale)
    filename = f"{_sanitize_filename(share.recording.title)}.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/{recording_id}", response_model=RecordingDetailResponse)
async def get_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> RecordingDetailResponse:
    """Get a recording with all details."""
    recording = await _load_recording_detail(recording_id, user.id, db)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    return _serialize_recording_detail(recording)


# ---- Export helpers ----


ExportLocale = Literal["en", "ru"]

_EXPORT_COPY: dict[ExportLocale, dict[str, str]] = {
    "en": {
        "untitled": "Untitled Recording",
        "date": "Date",
        "duration": "Duration",
        "type": "Type",
        "summary": "Summary",
        "highlights": "Key Highlights",
        "transcript": "Transcript",
        "unknown": "Unknown",
        "speaker": "Speaker",
    },
    "ru": {
        "untitled": "Запись без названия",
        "date": "Дата",
        "duration": "Длительность",
        "type": "Тип",
        "summary": "Саммари",
        "highlights": "Ключевые моменты",
        "transcript": "Расшифровка",
        "unknown": "Неизвестно",
        "speaker": "Спикер",
    },
}

_EXPORT_TYPE_LABELS: dict[ExportLocale, dict[str, str]] = {
    "en": {"meeting": "meeting", "note": "note", "reflection": "reflection"},
    "ru": {"meeting": "встреча", "note": "заметка", "reflection": "рефлексия"},
}

_EXPORT_HIGHLIGHT_LABELS: dict[ExportLocale, dict[str, str]] = {
    "en": {
        "decision": "Decision",
        "action": "Action",
        "question": "Question",
        "insight": "Insight",
    },
    "ru": {
        "decision": "Решение",
        "action": "Действие",
        "question": "Вопрос",
        "insight": "Инсайт",
    },
}

_SPEAKER_LABEL_RE = re.compile(r"^(speaker|спикер)[\s_-]*(\d+)$", re.IGNORECASE)


def _resolve_export_locale(recording: Recording, locale: ExportLocale | None) -> ExportLocale:
    if locale is not None:
        return locale
    language = (recording.language or "").strip().lower()
    return "ru" if language.startswith("ru") else "en"


def _humanize_speaker_label(label: str | None, locale: ExportLocale) -> str:
    raw = (label or "").strip()
    if not raw:
        return _EXPORT_COPY[locale]["unknown"]
    match = _SPEAKER_LABEL_RE.match(raw)
    if match is None:
        return raw
    raw_number = int(match.group(2))
    display_number = raw_number + 1 if raw_number == 0 or "_" in raw or "-" in raw else raw_number
    return f"{_EXPORT_COPY[locale]['speaker']} {display_number}"


def _segment_export_speaker(seg: Segment, locale: ExportLocale) -> str:
    if seg.person and seg.person.display_name:
        return seg.person.display_name
    return _humanize_speaker_label(seg.speaker or seg.raw_label, locale)


def _assigned_speaker_names(recording: Recording) -> dict[str, str]:
    """Map raw diarization labels (``speaker_0``) to their assigned Person name.

    Built from the recording's segments. Only labels that have been assigned to a
    Person are included, so renaming a speaker propagates into the stored summary
    and highlight text (which embed the raw ``speaker_N`` tokens from generation
    time) without regenerating them. Locale-independent.
    """
    mapping: dict[str, str] = {}
    for seg in recording.segments:
        raw = (seg.speaker or seg.raw_label or "").strip()
        if raw and raw not in mapping and seg.person and seg.person.display_name:
            mapping[raw] = seg.person.display_name
    return mapping


def _export_speaker_names(recording: Recording, locale: ExportLocale) -> dict[str, str]:
    """Map every raw diarization label to its best display name for export.

    Assigned labels resolve to the Person display name; unassigned labels resolve
    to the localized generic ("Говорящий 1" / "Speaker 1").
    """
    mapping: dict[str, str] = {}
    for seg in recording.segments:
        raw = (seg.speaker or seg.raw_label or "").strip()
        if not raw or raw in mapping:
            continue
        if seg.person and seg.person.display_name:
            mapping[raw] = seg.person.display_name
        else:
            mapping[raw] = _humanize_speaker_label(raw, locale)
    return mapping


def _apply_speaker_names(text: str | None, names: dict[str, str]) -> str | None:
    """Substitute raw speaker labels embedded in free text with display names.

    Longest labels first so ``speaker_1`` never rewrites inside ``speaker_10``.
    """
    if not text or not names:
        return text
    for raw in sorted(names, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(raw)}\b", names[raw], text)
    return text


def _highlight_category_label(category: str, locale: ExportLocale) -> str:
    normalized = (category or "").strip().lower()
    return _EXPORT_HIGHLIGHT_LABELS[locale].get(normalized, normalized.capitalize() or category)


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


def _format_recording_date(created_at: datetime, locale: ExportLocale) -> str:
    """Format recording creation date for export headers."""
    if locale == "ru":
        return created_at.strftime("%d.%m.%Y")
    return created_at.strftime("%B %d, %Y")


def _export_markdown(recording: Recording, locale: ExportLocale | None = None) -> str:
    """Export recording as Markdown."""
    resolved_locale = _resolve_export_locale(recording, locale)
    copy = _EXPORT_COPY[resolved_locale]
    lines: list[str] = []

    title = recording.title or copy["untitled"]
    lines.append(f"# {title}")

    # Metadata line
    date_str = _format_recording_date(recording.created_at, resolved_locale)
    duration_str = _format_duration_mmss(recording.duration_seconds)
    type_label = _EXPORT_TYPE_LABELS[resolved_locale].get(recording.type, recording.type)
    lines.append(
        f"*{copy['date']}: {date_str} | {copy['duration']}: {duration_str} | "
        f"{copy['type']}: {type_label}*"
    )
    lines.append("")

    names = _export_speaker_names(recording, resolved_locale)

    # Summary section (only if present)
    if recording.summary and recording.summary.summary:
        lines.append(f"## {copy['summary']}")
        lines.append(_apply_speaker_names(recording.summary.summary, names))
        lines.append("")

    # Key Highlights section (only if present)
    if recording.highlights:
        lines.append(f"## {copy['highlights']}")
        for h in sorted(recording.highlights, key=lambda x: x.start_ms or 0):
            if h.speaker:
                ts = _format_timestamp_short(h.start_ms)
                speaker = names.get(h.speaker) or _humanize_speaker_label(
                    h.speaker, resolved_locale
                )
                speaker_part = f" ({speaker}, {ts})"
            elif h.start_ms is not None:
                speaker_part = f" ({_format_timestamp_short(h.start_ms)})"
            else:
                speaker_part = ""
            category = _highlight_category_label(h.category, resolved_locale)
            lines.append(f"- **[{category}]** {h.title}{speaker_part}")
        lines.append("")

    # Transcript section
    lines.append(f"## {copy['transcript']}")
    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)
    for seg in segments:
        speaker = _segment_export_speaker(seg, resolved_locale)
        ts = _format_timestamp_short(seg.start_ms)
        ts_part = f" ({ts})" if ts else ""
        lines.append(f"**{speaker}**{ts_part}: {seg.content}")
    lines.append("")

    return "\n".join(lines)


def _export_txt(recording: Recording, locale: ExportLocale | None = None) -> str:
    """Export recording as plain text.

    Mirrors the Markdown export's sections (summary, highlights, transcript) so the
    three export formats are consistent (124); only the formatting differs.
    """
    resolved_locale = _resolve_export_locale(recording, locale)
    copy = _EXPORT_COPY[resolved_locale]
    names = _export_speaker_names(recording, resolved_locale)
    lines: list[str] = []

    title = recording.title or copy["untitled"]
    lines.append(title)

    date_str = _format_recording_date(recording.created_at, resolved_locale)
    duration_str = _format_duration_mmss(recording.duration_seconds)
    lines.append(f"{copy['date']}: {date_str} | {copy['duration']}: {duration_str}")
    lines.append("")

    # Summary section (parity with the Markdown export).
    if recording.summary and recording.summary.summary:
        lines.append(copy["summary"])
        lines.append(_apply_speaker_names(recording.summary.summary, names))
        lines.append("")

    # Key Highlights section.
    if recording.highlights:
        lines.append(copy["highlights"])
        for h in sorted(recording.highlights, key=lambda x: x.start_ms or 0):
            category = _highlight_category_label(h.category, resolved_locale)
            if h.speaker:
                ts = _format_timestamp_short(h.start_ms)
                speaker = names.get(h.speaker) or _humanize_speaker_label(
                    h.speaker, resolved_locale
                )
                suffix = f" ({speaker}, {ts})"
            elif h.start_ms is not None:
                suffix = f" ({_format_timestamp_short(h.start_ms)})"
            else:
                suffix = ""
            lines.append(f"- [{category}] {h.title}{suffix}")
        lines.append("")

    # Transcript section.
    lines.append(copy["transcript"])
    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)
    for seg in segments:
        speaker = _segment_export_speaker(seg, resolved_locale)
        ts = _format_timestamp_short(seg.start_ms)
        if ts:
            lines.append(f"[{speaker}, {ts}] {seg.content}")
        else:
            lines.append(f"[{speaker}] {seg.content}")
    lines.append("")

    return "\n".join(lines)


def _export_srt(recording: Recording, locale: ExportLocale | None = None) -> str:
    """Export recording as SRT subtitle format."""
    resolved_locale = _resolve_export_locale(recording, locale)
    segments = sorted(recording.segments, key=lambda s: s.start_ms or 0)
    if not segments:
        return ""

    entries: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start_ts = _format_timestamp_srt(seg.start_ms)
        end_ts = _format_timestamp_srt(seg.end_ms)
        speaker = _segment_export_speaker(seg, resolved_locale)
        entries.append(f"{i}")
        entries.append(f"{start_ts} --> {end_ts}")
        entries.append(f"[{speaker}] {seg.content}")
        entries.append("")

    return "\n".join(entries)


def _sanitize_filename(title: str | None) -> str:
    """Create a safe filename from a recording title.

    Preserves Unicode letters/digits but strips control characters and
    filesystem-unsafe characters (/ \\ : * ? \" < > |).
    """
    name = title or "recording"
    # Strip control characters and filesystem-unsafe characters
    safe = re.sub(r'[/\\:*?"<>|\x00-\x1f\x7f]', "", name)
    safe = safe.strip().replace(" ", "_")
    return safe[:100] or "recording"


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition header value safe for all browsers.

    Uses ASCII-only ``filename`` with unsafe characters stripped (not escaped)
    plus RFC 5987 ``filename*`` with UTF-8 percent-encoding so browsers that
    support it can display the full Unicode name.

    The ASCII fallback deliberately removes quotes, backslashes, and other
    characters that break the ``filename="..."`` token rather than attempting
    to escape them, because many HTTP clients/browsers handle escaped quotes
    inside Content-Disposition inconsistently.
    """
    # ASCII-safe fallback: replace non-ASCII with '_', strip characters
    # that are unsafe inside a quoted filename token (" \ and control chars)
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    ascii_name = re.sub(r'["\\\x00-\x1f\x7f]', "_", ascii_name)
    ascii_name = ascii_name.strip("_") or "download"

    # RFC 5987 UTF-8 percent-encoded version (encodes everything except
    # unreserved characters per RFC 3986)
    utf8_name = quote(filename, safe="")

    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{utf8_name}"
    )


@router.get("/{recording_id}/export")
async def export_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    format: Literal["markdown", "txt", "srt"] = Query(...),
    locale: Literal["en", "ru"] | None = Query(None),
) -> Response:
    """Export a recording transcript in the requested format."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(
            selectinload(Recording.segments).selectinload(Segment.person),
            selectinload(Recording.summary),
            selectinload(Recording.highlights),
        )
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if format == "markdown":
        content = _export_markdown(recording, locale)
        media_type = "text/markdown; charset=utf-8"
        ext = "md"
    elif format == "txt":
        content = _export_txt(recording, locale)
        media_type = "text/plain; charset=utf-8"
        ext = "txt"
    else:
        content = _export_srt(recording, locale)
        media_type = "text/srt; charset=utf-8"
        ext = "srt"

    filename = f"{_sanitize_filename(recording.title)}.{ext}"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.delete(
    "/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    permanent: bool = False,
) -> Response:
    """Delete a recording."""
    result = await db.execute(
        select(Recording).where(Recording.id == recording_id, Recording.user_id == user.id)
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if permanent or recording.deleted_at is not None:
        await db.delete(recording)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    recording.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


class StarRecordingResponse(BaseModel):
    """Response for starring/unstarring a recording."""

    id: str
    starred_at: datetime | None


@router.post("/{recording_id}/star", response_model=StarRecordingResponse)
async def star_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> StarRecordingResponse:
    """Star a recording."""
    recording = await _load_active_recording(recording_id, user.id, db)

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    recording.starred_at = datetime.now(timezone.utc)
    await db.flush()

    return StarRecordingResponse(id=str(recording.id), starred_at=recording.starred_at)


@router.delete("/{recording_id}/star", response_model=StarRecordingResponse)
async def unstar_recording(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> StarRecordingResponse:
    """Unstar a recording."""
    recording = await _load_active_recording(recording_id, user.id, db)

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    recording.starred_at = None
    await db.flush()

    return StarRecordingResponse(id=str(recording.id), starred_at=None)


@router.patch("/{recording_id}", response_model=RecordingResponse)
async def update_recording(
    recording_id: UUID,
    request: UpdateRecordingRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingResponse:
    """Update a recording."""
    recording = await _load_active_recording(recording_id, user.id, db)

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
        .options(selectinload(Recording.segments).selectinload(Segment.person))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    return [
        _serialize_segment(s)
        for s in sorted(recording.segments, key=lambda x: x.start_ms or 0)
    ]


@router.get("/{recording_id}/transcript/search", response_model=TranscriptSearchResponse)
async def search_transcript(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    q: str = Query(min_length=1),
    limit: int = Query(20, ge=1, le=200),
) -> TranscriptSearchResponse:
    """Search within a recording's transcript for matching segments."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.segments).selectinload(Segment.person))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    query_lower = q.lower()
    matches: list[TranscriptSearchMatch] = []

    for s in sorted(recording.segments, key=lambda x: x.start_ms or 0):
        count = s.content.lower().count(query_lower)
        if count > 0:
            matches.append(
                TranscriptSearchMatch(
                    segment_id=str(s.id),
                    speaker=s.speaker,
                    content=s.content,
                    start_ms=s.start_ms,
                    end_ms=s.end_ms,
                    match_count=count,
                )
            )

    return TranscriptSearchResponse(
        recording_id=str(recording_id),
        query=q,
        total_matches=len(matches),
        segments=matches[:limit],
    )


# English stop words for keyword extraction
_STOP_WORDS = frozenset(
    "a about above after again against all am an and any are aren't as at be because been "
    "before being below between both but by can't cannot could couldn't did didn't do does "
    "doesn't doing don't down during each few for from further get got had hadn't has hasn't "
    "have haven't having he he'd he'll he's her here here's hers herself him himself his how "
    "how's i i'd i'll i'm i've if in into is isn't it it's its itself just let's me might more "
    "most mustn't my myself no nor not of off on once only or other ought our ours ourselves "
    "out over own really same shan't she she'd she'll she's should shouldn't so some such than "
    "that that's the their theirs them themselves then there there's these they they'd they'll "
    "they're they've this those through to too under until up upon us very was wasn't we we'd "
    "we'll we're we've were weren't what what's when when's where where's which while who who's "
    "whom why why's will with won't would wouldn't yes yet you you'd you'll you're you've your "
    "yours yourself yourselves also going go like well think know right yeah okay sure thing "
    "want need um uh ah oh ok hey hi hello thanks thank great good".split()
)


@router.get("/{recording_id}/keywords", response_model=KeywordsResponse)
async def get_recording_keywords(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    limit: int = Query(20, ge=1, le=100),
) -> KeywordsResponse:
    """Extract key terms from a recording's transcript."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.segments).selectinload(Segment.person))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    # Collect all words from segments
    all_words: list[str] = []
    for segment in recording.segments:
        words = re.findall(r"[a-zA-Z]+", segment.content.lower())
        all_words.extend(words)

    total_words = len(all_words)

    # Filter stop words and short words
    meaningful = [w for w in all_words if w not in _STOP_WORDS and len(w) > 1]

    # Count frequencies
    counter = Counter(meaningful)
    top_terms = counter.most_common(limit)

    return KeywordsResponse(
        recording_id=str(recording_id),
        total_words=total_words,
        keywords=[KeywordItem(term=term, count=count) for term, count in top_terms],
    )


class TranscriptStatsResponse(BaseModel):
    """Aggregate statistics about a recording's transcript."""

    recording_id: str
    segment_count: int
    word_count: int
    unique_speakers: int
    speakers: list[str]
    avg_words_per_segment: float
    longest_segment_ms: int | None
    shortest_segment_ms: int | None


@router.get(
    "/{recording_id}/transcript-stats",
    response_model=TranscriptStatsResponse,
)
async def get_transcript_stats(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> TranscriptStatsResponse:
    """Get aggregate transcript statistics for a recording."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(selectinload(Recording.segments).selectinload(Segment.person))
    )
    recording = result.scalar_one_or_none()

    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found",
        )

    segments = recording.segments or []
    word_count = sum(len(s.content.split()) for s in segments)
    speakers_seen: list[str] = []
    for s in segments:
        if s.person is not None and s.person.display_name:
            name = s.person.display_name
        else:
            name = s.raw_label or s.speaker
        if name and name not in speakers_seen:
            speakers_seen.append(name)

    durations: list[int] = []
    for s in segments:
        if s.start_ms is not None and s.end_ms is not None:
            durations.append(s.end_ms - s.start_ms)

    avg_wps = round(word_count / len(segments), 1) if segments else 0.0

    return TranscriptStatsResponse(
        recording_id=str(recording_id),
        segment_count=len(segments),
        word_count=word_count,
        unique_speakers=len(speakers_seen),
        speakers=speakers_seen,
        avg_words_per_segment=avg_wps,
        longest_segment_ms=max(durations) if durations else None,
        shortest_segment_ms=min(durations) if durations else None,
    )


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
        .options(selectinload(Recording.segments).selectinload(Segment.person))
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

    # Group segments by effective speaker name (assigned Person → raw label → "Unknown")
    speaker_segments: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        if seg.person is not None and seg.person.display_name:
            name = seg.person.display_name
        else:
            name = seg.raw_label or seg.speaker or "Unknown"
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
            if last_spoke_ms is None or end > last_spoke_ms:
                last_spoke_ms = end

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
    bind_recording_context(str(recording_id))
    add_sentry_breadcrumb(
        category="recording",
        message="Saving transcript",
        data={"recording_id": str(recording_id), "segment_count": len(request.segments)},
    )
    logger.info("live transcript save started segment_count=%s", len(request.segments))
    if not any(segment.text.strip() for segment in request.segments):
        add_sentry_breadcrumb(
            category="recording",
            message="Saving empty live transcript",
            data={
                "recording_id": str(recording_id),
                "duration_seconds": request.duration_seconds,
            },
            level="warning",
        )
        logger.warning(
            "live transcript save received no non-empty segments duration_seconds=%s",
            request.duration_seconds,
        )
    user_id = user.id
    recording = await _load_recording_detail(recording_id, user_id, db, include_deleted=False)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if _has_canonical_audio_processing(recording):
        logger.warning(
            "ignored live transcript save for audio-backed recording "
            "status=%s incoming_segments=%s existing_segments=%s",
            recording.status,
            len(request.segments),
            len(recording.segments),
        )
        add_sentry_breadcrumb(
            category="recording",
            message="Ignored live transcript save for audio-backed recording",
            data={
                "recording_id": str(recording_id),
                "status": recording.status,
                "incoming_segments": len(request.segments),
                "existing_segments": len(recording.segments),
            },
            level="warning",
        )
        return _serialize_recording_detail(recording)

    try:
        await _persist_client_segments(
            recording,
            db,
            request.segments,
            duration_seconds=request.duration_seconds,
            fallback_language=user.default_language,
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
    refreshed = await _load_recording_detail(recording_id, user_id, db, include_deleted=False)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    logger.info(
        "live transcript save completed status=%s segment_count=%s",
        refreshed.status,
        len(request.segments),
    )
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


@router.get("/{recording_id}/summary-generation", response_model=SummaryGenerationResponse)
async def get_summary_generation(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SummaryGenerationResponse:
    """Get durable summary generation state for a recording."""
    result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(
            selectinload(Recording.summary),
            selectinload(Recording.summary_generation_jobs),
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    return _serialize_summary_generation(
        recording_id=recording.id,
        summary=recording.summary,
        job=latest_summary_generation_job(recording),
    )


@router.post(
    "/{recording_id}/summary-generation",
    response_model=SummaryGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_summary_generation(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
    request: StartSummaryGenerationRequest | None = Body(default=None),
) -> SummaryGenerationResponse:
    """Start or reuse durable summary generation for a recording."""
    recording_result = await db.execute(
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user.id)
        .options(
            selectinload(Recording.segments),
            selectinload(Recording.summary),
            selectinload(Recording.summary_generation_jobs),
        )
        .with_for_update()
    )
    recording = recording_result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not recording.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcript segments to summarize",
        )

    active_job = await load_active_summary_generation_job(
        db,
        recording_id=recording.id,
        user_id=user.id,
    )
    if active_job is not None:
        return _serialize_summary_generation(
            recording_id=recording.id,
            summary=recording.summary,
            job=active_job,
        )

    transcript = build_summary_transcript(recording.segments)
    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=summary_transcript_hash(transcript),
        instructions_override=request.instructions if request else None,
    )
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        active_job = await load_active_summary_generation_job(
            db,
            recording_id=recording_id,
            user_id=user.id,
        )
        if active_job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Summary generation already changed",
            )
        return _serialize_summary_generation(
            recording_id=recording_id,
            summary=None,
            job=active_job,
        )
    await db.commit()

    try:
        job.task_id = enqueue_summary_generation(job.id)
    except Exception as exc:
        logger.exception("Failed to enqueue summary generation for recording %s", recording_id)
        job.status = SummaryGenerationStatus.FAILED.value
        job.stage = "failed"
        job.progress_percent = 100
        job.error_code = "summary_enqueue_failed"
        job.error_message = "Failed to start summary generation."
        job.failed_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to start summary generation",
        ) from exc

    await db.commit()
    return _serialize_summary_generation(
        recording_id=recording.id,
        summary=recording.summary,
        job=job,
    )


class AssignSpeakerRequest(BaseModel):
    """Assign all segments matching ``raw_label`` in this recording to a Person."""

    raw_label: str = Field(min_length=1, max_length=100)
    person_id: UUID | None = None
    new_display_name: str | None = Field(default=None, min_length=1, max_length=200)


class RematchSpeakersResponse(BaseModel):
    """Result of running voice-ID rematch against current voiceprint library."""

    recording_id: str
    updated_clusters: int
    matched_clusters: int


@router.post(
    "/{recording_id}/assign-speaker",
    response_model=RecordingDetailResponse,
)
async def assign_speaker(
    recording_id: UUID,
    request: AssignSpeakerRequest,
    user: CurrentUser,
    db: Database,
) -> RecordingDetailResponse:
    """Map all segments with ``raw_label`` in this recording to a Person.

    Creates the Person if ``new_display_name`` is provided; otherwise resolves
    ``person_id``. Marks every touched segment as user-confirmed
    (``auto_assigned=False``) and clears ``match_confidence``.
    """
    if (request.person_id is None) == (request.new_display_name is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of person_id or new_display_name",
        )

    recording_result = await db.execute(
        select(Recording).where(
            Recording.id == recording_id, Recording.user_id == user.id
        )
    )
    recording = recording_result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if request.person_id is not None:
        person_result = await db.execute(
            select(Person).where(
                Person.id == request.person_id, Person.user_id == user.id
            )
        )
        person = person_result.scalar_one_or_none()
        if person is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            )
    else:
        person = Person(
            user_id=user.id, display_name=request.new_display_name or ""
        )
        db.add(person)
        await db.flush()

    await db.execute(
        update(Segment)
        .where(
            Segment.recording_id == recording_id,
            Segment.raw_label == request.raw_label,
        )
        .values(person_id=person.id, auto_assigned=False, match_confidence=None)
    )
    await db.flush()
    voiceprint_id = await store_voiceprint_from_recording_speaker(
        db=db,
        user_id=user.id,
        person_id=person.id,
        recording_id=recording_id,
        raw_label=request.raw_label,
    )
    add_sentry_breadcrumb(
        category="recording",
        message="Speaker assignment completed",
        data={
            "recording_id": str(recording_id),
            "voiceprint_promoted": voiceprint_id is not None,
        },
    )

    detail = await _load_recording_detail(recording_id, user.id, db)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    return _serialize_recording_detail(detail)


@router.post(
    "/{recording_id}/rematch",
    response_model=RematchSpeakersResponse,
)
async def rematch_speakers(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> RematchSpeakersResponse:
    """Re-run voice-ID matching against the current voiceprint library.

    Touches only clusters where ``auto_assigned=True`` or ``person_id IS NULL``
    so user-confirmed assignments are preserved.

    Returns 422 for older or realtime-only recordings that do not have retained
    per-speaker voice embeddings. Source audio is still deleted after processing.
    """
    recording_result = await db.execute(
        select(Recording.id).where(
            Recording.id == recording_id,
            Recording.user_id == user.id,
        )
    )
    if recording_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    rematch = await rematch_recording_speakers(
        db=db,
        user_id=user.id,
        recording_id=recording_id,
    )
    if rematch is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No speaker voice embeddings are stored for this recording; "
                "rematch is only available for audio-backed recordings processed "
                "after voice identification was enabled."
            ),
        )
    await db.commit()
    return RematchSpeakersResponse(
        recording_id=str(recording_id),
        updated_clusters=rematch.updated_clusters,
        matched_clusters=rematch.matched_clusters,
    )


@router.post("/{recording_id}/generate-summary", response_model=SummaryResponse)
async def generate_summary(
    recording_id: UUID,
    user: CurrentUser,
    db: Database,
) -> SummaryResponse:
    """Generate or regenerate AI summary for a recording."""
    add_sentry_breadcrumb(
        category="recording",
        message="Generating summary",
        data={"recording_id": str(recording_id)},
    )
    recording = await _load_recording_detail(recording_id, user.id, db, include_deleted=False)

    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not recording.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcript segments to summarize",
        )

    transcript = build_summary_transcript(recording.segments)
    summary_language = resolve_summary_language_preference(
        user.summary_language,
        recording.language,
        user.default_language,
    )
    summary_style = resolve_summary_style_preference(user.summary_style)

    try:
        summary_result = await summarize_transcript(
            transcript,
            language=summary_language,
            style=summary_style,
            instructions=combine_summary_instructions(
                base_instructions=user.summary_instructions,
                personalization_instructions=await summary_personalization_instructions(
                    db,
                    user_id=user.id,
                ),
            ),
            usage_user_id=user.id,
            usage_recording_id=recording.id,
        )

        await apply_summary_result(db, recording=recording, summary_result=summary_result)

        summary = _serialize_summary(recording.summary)
        if summary is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Summary not saved",
            )
        return summary
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Summary generation failed for recording %s", recording_id)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We couldn't generate the summary right now. Please try again in a moment.",
        ) from exc


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
    user: CurrentUser,
    db: Database,
    file: UploadFile = File(...),
    client_duration_seconds: int | None = Form(default=None),
    client_file_size_bytes: int | None = Form(default=None),
) -> RecordingDetailResponse:
    """Upload an imported audio file to an existing recording."""
    bind_recording_context(str(recording_id))
    add_sentry_breadcrumb(
        category="recording",
        message="Uploading audio file",
        data={"recording_id": str(recording_id), **safe_filename_metadata(file.filename)},
    )
    logger.info(
        "audio upload started filename=%s client_duration_seconds=%s client_file_size_bytes=%s",
        safe_text_digest(file.filename or "", label="filename"),
        client_duration_seconds,
        client_file_size_bytes,
    )
    # Validate recording exists and belongs to user
    user_id = user.id
    user_default_language = user.default_language
    recording = await _load_recording_detail(recording_id, user_id, db, include_deleted=False)
    if recording is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if _has_canonical_audio_processing(recording):
        await file.close()
        logger.warning(
            "ignored duplicate audio upload for audio-backed recording "
            "status=%s existing_segments=%s",
            recording.status,
            len(recording.segments),
        )
        add_sentry_breadcrumb(
            category="recording",
            message="Ignored duplicate audio upload for audio-backed recording",
            data={
                "recording_id": str(recording_id),
                "status": recording.status,
                "existing_segments": len(recording.segments),
            },
            level="warning",
        )
        return _serialize_recording_detail(recording)

    filename = file.filename or ""
    try:
        ext = _extension_from_upload(filename, file.content_type or "")
    except HTTPException as exc:
        await _mark_recording_failed(
            recording,
            db,
            "unsupported_file_type",
            _normalize_failure_message(str(exc.detail), "Unsupported file type"),
        )
        raise

    upload_size = _measure_upload_size(file)
    if upload_size > MAX_UPLOAD_SIZE:
        detail = _upload_limit_message()
        await _mark_recording_failed(recording, db, "file_too_large", detail)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=detail,
        )

    content_type = EXTENSION_TO_CONTENT_TYPE.get(
        ext,
        file.content_type or "application/octet-stream",
    )

    if not await _claim_audio_upload(recording_id, user_id, db):
        await file.close()
        db.expire_all()
        existing_recording = await _load_recording_detail(
            recording_id,
            user_id,
            db,
            include_deleted=False,
        )
        if existing_recording is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
        logger.warning(
            "ignored duplicate audio upload after claim race status=%s existing_segments=%s",
            existing_recording.status,
            len(existing_recording.segments),
        )
        add_sentry_breadcrumb(
            category="recording",
            message="Ignored duplicate audio upload after claim race",
            data={
                "recording_id": str(recording_id),
                "status": existing_recording.status,
                "existing_segments": len(existing_recording.segments),
            },
            level="warning",
        )
        return _serialize_recording_detail(existing_recording)

    db.expire_all()
    recording = await _load_recording_detail(recording_id, user_id, db, include_deleted=False)
    if recording is None:
        await file.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    try:
        staged_path, staged_size_bytes = await _stage_upload_to_disk(
            file=file,
            user_id=user_id,
            recording_id=recording_id,
            ext=ext,
        )
        if (
            client_file_size_bytes is not None
            and client_file_size_bytes != staged_size_bytes
        ):
            delete_staged_file(staged_path)
            detail = "Uploaded file size did not match the recorded file size."
            await _mark_recording_failed(recording, db, "upload_size_mismatch", detail)
            alert_data = {
                "alert_code": "recording.upload.size_mismatch",
                "recording_id": str(recording_id),
                "client_file_size_bytes": client_file_size_bytes,
                "staged_size_bytes": staged_size_bytes,
            }
            add_sentry_breadcrumb(
                category="recording",
                message="Audio upload size mismatch",
                level="warning",
                data=alert_data,
            )
            capture_sentry_message(
                "Audio upload size mismatch",
                level="warning",
                extras=alert_data,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            if exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
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
        db.expire_all()
        failed_recording = await _load_recording_detail(
            recording_id,
            user_id,
            db,
            include_deleted=True,
        )
        if failed_recording is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=detail,
            ) from exc
        return _serialize_recording_detail(failed_recording)

    recording.status = RecordingStatus.PROCESSING.value
    recording.failure_code = None
    recording.failure_message = None
    recording.audio_url = None
    recording.duration_seconds = None
    await db.commit()

    try:
        await enqueue_recording_audio_processing(
            recording_id=recording_id,
            user_id=user_id,
            staged_path=staged_path,
            content_type=content_type,
            user_default_language=user_default_language,
            client_duration_seconds=client_duration_seconds,
            client_file_size_bytes=client_file_size_bytes,
            staged_size_bytes=staged_size_bytes,
        )
    except Exception as exc:
        logger.exception("Failed to enqueue recording processing for %s", recording_id)
        await db.rollback()
        await _mark_recording_failed_by_id(
            recording_id,
            db,
            "processing_enqueue_failed",
            "Failed to start recording processing",
        )
        delete_staged_file(staged_path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to start recording processing",
        ) from exc

    db.expire_all()
    recording = await _load_recording_detail(recording_id, user_id, db, include_deleted=True)
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Recording disappeared after upload",
        )

    logger.info(
        "audio upload accepted for async processing status=%s staged_size_bytes=%s "
        "client_file_size_bytes=%s client_duration_seconds=%s",
        recording.status,
        staged_size_bytes,
        client_file_size_bytes,
        client_duration_seconds,
    )
    add_sentry_breadcrumb(
        category="recording",
        message="Audio upload accepted for async processing",
        data={
            "recording_id": str(recording_id),
            "status": recording.status,
            "staged_size_bytes": staged_size_bytes,
            "client_file_size_bytes": client_file_size_bytes,
            "client_duration_seconds": client_duration_seconds,
        },
    )
    return _serialize_recording_detail(recording)
