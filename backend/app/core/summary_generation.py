"""Durable recording summary generation helpers."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, defer, selectinload

from app.core.entity_graph import seed_entities_from_extraction, seed_entities_from_summary
from app.core.personalization import summary_personalization_instructions
from app.core.summarizer import (
    SummaryResult,
    extract_entities,
    resolve_highlight_timestamps,
    summarize_transcript,
)
from app.models.highlight import Highlight
from app.models.recording import (
    ActionItem,
    Recording,
    RecordingStatus,
    Segment,
    Summary,
    SummaryGenerationJob,
    SummaryGenerationStatus,
)
from app.models.user import User

logger = logging.getLogger(__name__)

# Cap the transcript fed to entity extraction (the +1 Cerebras call) so token
# cost stays bounded on long recordings.
_ENTITY_EXTRACTION_TRANSCRIPT_CAP = 24000

ACTIVE_SUMMARY_GENERATION_STATUSES = {
    SummaryGenerationStatus.QUEUED.value,
    SummaryGenerationStatus.RUNNING.value,
}
WAITING_FOR_TRANSCRIPT_STAGE = "waiting_for_transcript"
WAITING_FOR_TRANSCRIPT_HASH = hashlib.sha256(b"").hexdigest()
WAIT_FOR_TRANSCRIPT_RECORDING_STATUSES = (
    RecordingStatus.PENDING_UPLOAD.value,
    RecordingStatus.UPLOADING.value,
    RecordingStatus.PROCESSING.value,
)
SUMMARY_GENERATION_MAX_STALE_RUNNING_ATTEMPTS = 4
ORPHANED_SUMMARY_GENERATION_REENQUEUE_AFTER = timedelta(seconds=30)


class SummaryGenerationEnqueueError(RuntimeError):
    """Raised when a summary job was created but could not be enqueued."""


@dataclass(frozen=True)
class SummaryGenerationPayload:
    job_id: UUID
    recording_id: UUID
    user_id: UUID
    transcript: str
    transcript_hash: str
    language: str
    style: str
    instructions: str | None


def build_summary_transcript(segments: list[Segment]) -> str:
    lines: list[str] = []
    for segment in sorted(segments, key=lambda item: item.start_ms or 0):
        speaker = segment.speaker or "Speaker"
        lines.append(f"{speaker}: {segment.content}")
    return "\n".join(lines)


def summary_transcript_hash(transcript: str) -> str:
    return hashlib.sha256(transcript.encode("utf-8")).hexdigest()


def can_wait_for_transcript(recording: Recording) -> bool:
    return recording.status in WAIT_FOR_TRANSCRIPT_RECORDING_STATUSES


def is_orphaned_queued_summary_job(job: SummaryGenerationJob) -> bool:
    if job.status != SummaryGenerationStatus.QUEUED.value or job.task_id:
        return False
    if job.stage == WAITING_FOR_TRANSCRIPT_STAGE:
        return False
    queued_at = job.requested_at or job.created_at
    if queued_at is None:
        return True
    if queued_at.tzinfo is None:
        queued_at = queued_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - queued_at >= ORPHANED_SUMMARY_GENERATION_REENQUEUE_AFTER


def resolve_summary_language_preference(
    preferred_language: str | None,
    recording_language: str | None,
    default_language: str | None,
) -> str:
    """Choose the summary language, defaulting to the transcript language."""
    normalized_preference = (preferred_language or "").strip().lower()
    if normalized_preference and normalized_preference != "auto":
        return normalized_preference

    normalized_recording_language = (recording_language or "").strip().lower()
    if normalized_recording_language and normalized_recording_language != "multi":
        return normalized_recording_language

    normalized_default_language = (default_language or "").strip().lower()
    if normalized_default_language and normalized_default_language not in {"auto", "multi"}:
        return normalized_default_language

    return "auto"


def resolve_summary_style_preference(preferred_style: str | None) -> str:
    """Use the saved style when present; otherwise fall back to the default style."""
    normalized_style = (preferred_style or "").strip().lower()
    if normalized_style in {"brief", "medium", "detailed"}:
        return normalized_style
    return "medium"


def combine_summary_instructions(
    *,
    base_instructions: str | None,
    personalization_instructions: str | None,
    override_instructions: str | None = None,
) -> str | None:
    blocks = [
        value.strip()
        for value in (
            base_instructions,
            personalization_instructions,
            override_instructions,
        )
        if value and value.strip()
    ]
    return "\n\n".join(blocks) or None


async def load_active_summary_generation_job(
    db: AsyncSession,
    *,
    recording_id: UUID,
    user_id: UUID,
) -> SummaryGenerationJob | None:
    result = await db.execute(
        select(SummaryGenerationJob)
        .where(
            SummaryGenerationJob.recording_id == recording_id,
            SummaryGenerationJob.user_id == user_id,
            SummaryGenerationJob.status.in_(ACTIVE_SUMMARY_GENERATION_STATUSES),
        )
        .order_by(SummaryGenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fail_active_summary_generation_jobs(
    db: AsyncSession,
    *,
    recording_id: UUID,
    user_id: UUID | None = None,
    error_code: str,
    error_message: str,
    preserve_waiting_for_transcript: bool = False,
) -> list[SummaryGenerationJob]:
    """Fail queued/running summary jobs that are no longer valid."""
    conditions = [
        SummaryGenerationJob.recording_id == recording_id,
        SummaryGenerationJob.status.in_(ACTIVE_SUMMARY_GENERATION_STATUSES),
    ]
    if user_id is not None:
        conditions.append(SummaryGenerationJob.user_id == user_id)
    if preserve_waiting_for_transcript:
        conditions.append(SummaryGenerationJob.stage != WAITING_FOR_TRANSCRIPT_STAGE)

    jobs = (
        (
            await db.execute(
                select(SummaryGenerationJob)
                .where(*conditions)
                .order_by(SummaryGenerationJob.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        mark_summary_generation_failed(
            job,
            error_code=error_code,
            error_message=error_message,
        )
    if jobs:
        await db.flush()
    return list(jobs)


def latest_summary_generation_job(recording: Recording) -> SummaryGenerationJob | None:
    jobs = list(getattr(recording, "summary_generation_jobs", []) or [])
    if not jobs:
        return None
    return max(jobs, key=lambda job: job.created_at or job.requested_at)


async def apply_summary_result(
    db: AsyncSession,
    *,
    recording: Recording,
    summary_result: SummaryResult,
    entity_extractor=None,
    enrich_entities: bool = True,
) -> Summary:
    if recording.summary:
        recording.summary.summary = summary_result.summary
        recording.summary.key_points = summary_result.key_points
        recording.summary.decisions = summary_result.decisions
        recording.summary.topics = summary_result.topics
        recording.summary.people_mentioned = summary_result.people_mentioned
        recording.summary.sentiment = summary_result.sentiment
        summary = recording.summary
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

    # Legacy/system-owned titles may still reach summary generation without a
    # completed title pass. Resolve them once; filenames and manual names carry
    # title_auto_generated=False and are never clobbered.
    if recording.title_auto_generated:
        recording.title = summary_result.title
        recording.title_auto_generated = False

    await db.execute(
        delete(ActionItem).where(
            ActionItem.recording_id == recording.id,
            ActionItem.source == "generated",
        )
    )

    for item in summary_result.action_items:
        task = str(item.get("task", "")).strip()
        if not task:
            continue

        due_date = _parse_due_date(item.get("due"))
        priority = item.get("priority", "medium")
        if priority not in {"high", "medium", "low"}:
            priority = "medium"

        db.add(
            ActionItem(
                recording_id=recording.id,
                task=task,
                owner=item.get("owner"),
                due_date=due_date,
                priority=priority,
                source="generated",
            )
        )

    await db.execute(delete(Highlight).where(Highlight.recording_id == recording.id))
    await _add_summary_highlights(db, recording=recording, summary_result=summary_result)
    recording.updated_at = datetime.now(timezone.utc)
    await db.flush()

    if enrich_entities:
        await enrich_recording_entities_from_summary(
            db,
            recording=recording,
            summary_result=summary_result,
            entity_extractor=entity_extractor,
        )
    return summary


async def enrich_recording_entities_from_summary(
    db: AsyncSession,
    *,
    recording: Recording,
    summary_result: SummaryResult,
    entity_extractor=None,
) -> None:
    # Wire the knowledge graph from the transcript: rich, TYPED entities
    # (person / project / topic / organization) plus entity->entity relations,
    # so entity wiki pages render a populated "related" section. Extraction is
    # the +1 Cerebras call; if it fails we keep the zero-cost summary seed
    # (people/topics) so the recording still joins the graph — the failure is
    # logged, never silently swallowed.
    extractor = entity_extractor or extract_entities
    try:
        transcript = build_summary_transcript(recording.segments)
        extracted = (
            await extractor(transcript[:_ENTITY_EXTRACTION_TRANSCRIPT_CAP]) if transcript else []
        )
        await seed_entities_from_extraction(
            db,
            recording.user_id,
            source_kind="recording",
            source_id=recording.id,
            entities=extracted,
            recording_id=recording.id,
        )
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort; keep the floor
        logger.warning(
            "entity extraction failed recording=%s err=%s; seeding from summary",
            recording.id,
            exc,
        )
        await seed_entities_from_summary(
            db,
            recording.user_id,
            source_kind="recording",
            source_id=recording.id,
            people=summary_result.people_mentioned,
            topics=summary_result.topics,
        )


async def start_recording_summary_generation_job(
    db: AsyncSession,
    *,
    recording_id: UUID,
    user_id: UUID,
    enqueue: Callable[[UUID], str],
    instructions_override: str | None = None,
    skip_if_summary_exists: bool = False,
    raise_on_enqueue_error: bool = True,
) -> SummaryGenerationJob | None:
    """Create and enqueue a durable summary job for the current transcript.

    Returns ``None`` when the recording is missing or has no transcript segments.
    The job row is committed before the Celery task is enqueued so workers can
    load it immediately. Enqueue failures are written to the job row; callers can
    choose whether to surface them as request errors.
    """
    recording = await _load_recording_for_generation(
        db,
        recording_id=recording_id,
        user_id=user_id,
        include_outputs=True,
        lock=True,
    )
    if recording is None:
        return None

    if skip_if_summary_exists and recording.summary is not None:
        return latest_summary_generation_job(recording)

    active_job = await load_active_summary_generation_job(
        db,
        recording_id=recording.id,
        user_id=user_id,
    )

    if not recording.segments:
        if not can_wait_for_transcript(recording):
            return None
        if active_job is not None:
            if active_job.stage != WAITING_FOR_TRANSCRIPT_STAGE:
                active_job.stage = WAITING_FOR_TRANSCRIPT_STAGE
                active_job.progress_percent = 5
            if instructions_override is not None:
                active_job.instructions_override = instructions_override
            await db.commit()
            return active_job

        job = SummaryGenerationJob(
            recording_id=recording.id,
            user_id=user_id,
            status=SummaryGenerationStatus.QUEUED.value,
            stage=WAITING_FOR_TRANSCRIPT_STAGE,
            progress_percent=5,
            transcript_hash=WAITING_FOR_TRANSCRIPT_HASH,
            instructions_override=instructions_override,
        )
        db.add(job)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            active_job = await load_active_summary_generation_job(
                db,
                recording_id=recording_id,
                user_id=user_id,
            )
            if active_job is not None:
                return active_job
            raise

        await db.commit()
        return job

    transcript = build_summary_transcript(recording.segments)
    transcript_hash = summary_transcript_hash(transcript)

    if active_job is not None:
        if active_job.stage == WAITING_FOR_TRANSCRIPT_STAGE:
            active_job.transcript_hash = transcript_hash
            active_job.stage = "queued"
            active_job.progress_percent = 5
            active_job.error_code = None
            active_job.error_message = None
            active_job.failed_at = None
            if instructions_override is not None:
                active_job.instructions_override = instructions_override
            await db.commit()

            try:
                active_job.task_id = enqueue(active_job.id)
            except Exception as exc:  # noqa: BLE001 - broker failure is persisted below.
                mark_summary_generation_failed(
                    active_job,
                    error_code="summary_enqueue_failed",
                    error_message="Failed to start summary generation.",
                )
                await db.commit()
                if raise_on_enqueue_error:
                    raise SummaryGenerationEnqueueError(
                        "Failed to start summary generation"
                    ) from exc
                return active_job

            await db.commit()
            return active_job
        if active_job.transcript_hash == transcript_hash:
            if is_orphaned_queued_summary_job(active_job):
                active_job.stage = "queued"
                active_job.progress_percent = 5
                active_job.error_code = None
                active_job.error_message = None
                active_job.failed_at = None
                if instructions_override is not None:
                    active_job.instructions_override = instructions_override
                await db.commit()

                try:
                    active_job.task_id = enqueue(active_job.id)
                except Exception as exc:  # noqa: BLE001 - broker failure is persisted below.
                    mark_summary_generation_failed(
                        active_job,
                        error_code="summary_enqueue_failed",
                        error_message="Failed to start summary generation.",
                    )
                    await db.commit()
                    if raise_on_enqueue_error:
                        raise SummaryGenerationEnqueueError(
                            "Failed to start summary generation"
                        ) from exc
                    return active_job

                await db.commit()
            return active_job
        mark_summary_generation_failed(
            active_job,
            error_code="stale_transcript",
            error_message="Transcript changed before summary generation started.",
        )
        await db.flush()

    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user_id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=transcript_hash,
        instructions_override=instructions_override,
    )
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        active_job = await load_active_summary_generation_job(
            db,
            recording_id=recording_id,
            user_id=user_id,
        )
        if active_job is not None:
            return active_job
        raise

    await db.commit()

    try:
        job.task_id = enqueue(job.id)
    except Exception as exc:  # noqa: BLE001 - broker failure is persisted below.
        mark_summary_generation_failed(
            job,
            error_code="summary_enqueue_failed",
            error_message="Failed to start summary generation.",
        )
        await db.commit()
        if raise_on_enqueue_error:
            raise SummaryGenerationEnqueueError("Failed to start summary generation") from exc
        return job

    await db.commit()
    return job


async def recover_missing_summary_generation_jobs(
    db: AsyncSession,
    *,
    enqueue: Callable[[UUID], str],
    limit: int = 5,
    running_stale_after_minutes: int = 45,
) -> int:
    """Enqueue summaries for ready recordings that have no runnable task."""
    if limit <= 0:
        return 0
    running_stale_cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=running_stale_after_minutes
    )

    has_segments = select(Segment.id).where(Segment.recording_id == Recording.id).limit(1).exists()
    has_summary = select(Summary.id).where(Summary.recording_id == Recording.id).limit(1).exists()
    has_summary_job = (
        select(SummaryGenerationJob.id)
        .where(SummaryGenerationJob.recording_id == Recording.id)
        .limit(1)
        .exists()
    )
    active_summary_job = aliased(SummaryGenerationJob)
    has_active_summary_job = (
        select(active_summary_job.id)
        .where(
            active_summary_job.recording_id == Recording.id,
            active_summary_job.status.in_(ACTIVE_SUMMARY_GENERATION_STATUSES),
        )
        .limit(1)
        .exists()
    )
    recovered = 0

    failed_enqueue_jobs = (
        (
            await db.execute(
                select(SummaryGenerationJob)
                .join(Recording, Recording.id == SummaryGenerationJob.recording_id)
                .where(
                    SummaryGenerationJob.status == SummaryGenerationStatus.FAILED.value,
                    SummaryGenerationJob.error_code == "summary_enqueue_failed",
                    SummaryGenerationJob.task_id.is_(None),
                    has_segments,
                    ~has_summary,
                    ~has_active_summary_job,
                )
                .options(
                    selectinload(SummaryGenerationJob.recording)
                    .selectinload(Recording.segments)
                    .options(defer(Segment.embedding))
                )
                .order_by(
                    SummaryGenerationJob.failed_at.asc().nulls_last(),
                    SummaryGenerationJob.created_at.asc(),
                    SummaryGenerationJob.id.asc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for job in failed_enqueue_jobs:
        transcript_hash = summary_transcript_hash(build_summary_transcript(job.recording.segments))
        if transcript_hash != job.transcript_hash:
            mark_summary_generation_failed(
                job,
                error_code="stale_transcript",
                error_message="Transcript changed before summary generation started.",
            )
            await db.commit()
            continue

        job.status = SummaryGenerationStatus.QUEUED.value
        job.stage = "queued"
        job.progress_percent = 5
        job.error_code = None
        job.error_message = None
        job.failed_at = None
        try:
            job.task_id = enqueue(job.id)
        except Exception:  # noqa: BLE001 - broker failure is persisted below.
            mark_summary_generation_failed(
                job,
                error_code="summary_enqueue_failed",
                error_message="Failed to start summary generation.",
            )
            await db.commit()
            continue
        await db.commit()
        recovered += 1

    remaining_limit = limit - recovered
    if remaining_limit <= 0:
        return recovered

    stale_running_jobs = (
        (
            await db.execute(
                select(SummaryGenerationJob)
                .join(Recording, Recording.id == SummaryGenerationJob.recording_id)
                .where(
                    SummaryGenerationJob.status == SummaryGenerationStatus.RUNNING.value,
                    SummaryGenerationJob.started_at.is_not(None),
                    SummaryGenerationJob.started_at <= running_stale_cutoff,
                    has_segments,
                    ~has_summary,
                )
                .options(
                    selectinload(SummaryGenerationJob.recording)
                    .selectinload(Recording.segments)
                    .options(defer(Segment.embedding))
                )
                .order_by(SummaryGenerationJob.started_at.asc(), SummaryGenerationJob.id.asc())
                .limit(remaining_limit)
            )
        )
        .scalars()
        .all()
    )
    for job in stale_running_jobs:
        transcript_hash = summary_transcript_hash(build_summary_transcript(job.recording.segments))
        if transcript_hash != job.transcript_hash:
            mark_summary_generation_failed(
                job,
                error_code="stale_transcript",
                error_message="Transcript changed while summary generation was running.",
            )
            await db.commit()
            continue

        if job.attempt_count >= SUMMARY_GENERATION_MAX_STALE_RUNNING_ATTEMPTS:
            mark_summary_generation_failed(
                job,
                error_code="summary_worker_lost",
                error_message="Summary generation stopped before finishing. Please try again.",
            )
            await db.commit()
            continue

        job.status = SummaryGenerationStatus.QUEUED.value
        job.stage = "queued"
        job.progress_percent = 5
        job.task_id = None
        job.started_at = None
        job.error_code = None
        job.error_message = None
        job.failed_at = None
        try:
            job.task_id = enqueue(job.id)
        except Exception:  # noqa: BLE001 - broker failure is persisted below.
            mark_summary_generation_failed(
                job,
                error_code="summary_enqueue_failed",
                error_message="Failed to start summary generation.",
            )
            await db.commit()
            continue
        await db.commit()
        recovered += 1

    remaining_limit = limit - recovered
    if remaining_limit <= 0:
        return recovered

    orphaned_jobs = (
        (
            await db.execute(
                select(SummaryGenerationJob)
                .join(Recording, Recording.id == SummaryGenerationJob.recording_id)
                .where(
                    SummaryGenerationJob.status == SummaryGenerationStatus.QUEUED.value,
                    SummaryGenerationJob.stage != WAITING_FOR_TRANSCRIPT_STAGE,
                    SummaryGenerationJob.task_id.is_(None),
                    has_segments,
                    ~has_summary,
                )
                .options(
                    selectinload(SummaryGenerationJob.recording)
                    .selectinload(Recording.segments)
                    .options(defer(Segment.embedding))
                )
                .order_by(SummaryGenerationJob.created_at.asc(), SummaryGenerationJob.id.asc())
                .limit(remaining_limit)
            )
        )
        .scalars()
        .all()
    )
    for job in orphaned_jobs:
        transcript_hash = summary_transcript_hash(build_summary_transcript(job.recording.segments))
        if transcript_hash != job.transcript_hash:
            mark_summary_generation_failed(
                job,
                error_code="stale_transcript",
                error_message="Transcript changed before summary generation started.",
            )
            await db.commit()
            continue
        try:
            job.task_id = enqueue(job.id)
        except Exception:  # noqa: BLE001 - broker failure is persisted below.
            mark_summary_generation_failed(
                job,
                error_code="summary_enqueue_failed",
                error_message="Failed to start summary generation.",
            )
            await db.commit()
            continue
        await db.commit()
        recovered += 1

    remaining_limit = limit - recovered
    if remaining_limit <= 0:
        return recovered

    terminal_waiting_jobs = (
        (
            await db.execute(
                select(SummaryGenerationJob)
                .join(Recording, Recording.id == SummaryGenerationJob.recording_id)
                .where(
                    SummaryGenerationJob.status == SummaryGenerationStatus.QUEUED.value,
                    SummaryGenerationJob.stage == WAITING_FOR_TRANSCRIPT_STAGE,
                    Recording.status.notin_(WAIT_FOR_TRANSCRIPT_RECORDING_STATUSES),
                    ~has_segments,
                )
                .order_by(SummaryGenerationJob.created_at.asc(), SummaryGenerationJob.id.asc())
                .limit(remaining_limit)
            )
        )
        .scalars()
        .all()
    )
    for job in terminal_waiting_jobs:
        mark_summary_generation_failed(
            job,
            error_code="no_transcript_segments",
            error_message="No transcript segments to summarize.",
        )
        await db.commit()

    waiting_rows = (
        await db.execute(
            select(SummaryGenerationJob.recording_id, SummaryGenerationJob.user_id)
            .join(Recording, Recording.id == SummaryGenerationJob.recording_id)
            .where(
                SummaryGenerationJob.status == SummaryGenerationStatus.QUEUED.value,
                SummaryGenerationJob.stage == WAITING_FOR_TRANSCRIPT_STAGE,
                has_segments,
                ~has_summary,
            )
            .order_by(SummaryGenerationJob.created_at.asc(), SummaryGenerationJob.id.asc())
            .limit(remaining_limit)
        )
    ).all()
    for recording_id, user_id in waiting_rows:
        job = await start_recording_summary_generation_job(
            db,
            recording_id=recording_id,
            user_id=user_id,
            enqueue=enqueue,
            skip_if_summary_exists=True,
            raise_on_enqueue_error=False,
        )
        if job is not None and job.status in ACTIVE_SUMMARY_GENERATION_STATUSES:
            recovered += 1

    remaining_limit = limit - recovered
    if remaining_limit <= 0:
        return recovered

    rows = (
        await db.execute(
            select(Recording.id, Recording.user_id)
            .where(
                Recording.status == RecordingStatus.READY.value,
                has_segments,
                ~has_summary,
                ~has_summary_job,
            )
            .order_by(Recording.created_at.desc(), Recording.id.asc())
            .limit(remaining_limit)
        )
    ).all()

    for recording_id, user_id in rows:
        job = await start_recording_summary_generation_job(
            db,
            recording_id=recording_id,
            user_id=user_id,
            enqueue=enqueue,
            skip_if_summary_exists=True,
            raise_on_enqueue_error=False,
        )
        if job is not None and job.status in ACTIVE_SUMMARY_GENERATION_STATUSES:
            recovered += 1

    return recovered


async def prepare_summary_generation_payload(
    db: AsyncSession,
    *,
    job_id: UUID,
    task_id: str | None = None,
) -> SummaryGenerationPayload | None:
    job = await _load_job_for_update(db, job_id)
    if job is None or job.status not in ACTIVE_SUMMARY_GENERATION_STATUSES:
        return None

    recording = await _load_recording_for_generation(
        db,
        recording_id=job.recording_id,
        user_id=job.user_id,
        include_outputs=False,
    )
    user = await db.get(User, job.user_id)
    if recording is None or user is None:
        mark_summary_generation_failed(
            job,
            error_code="recording_not_found",
            error_message="Recording not found.",
        )
        return None

    if not recording.segments:
        if job.stage == WAITING_FOR_TRANSCRIPT_STAGE:
            job.status = SummaryGenerationStatus.QUEUED.value
            job.progress_percent = 5
            job.task_id = task_id or job.task_id
            return None
        mark_summary_generation_failed(
            job,
            error_code="no_transcript_segments",
            error_message="No transcript segments to summarize.",
        )
        return None

    transcript = build_summary_transcript(recording.segments)
    transcript_hash = summary_transcript_hash(transcript)
    if job.stage == WAITING_FOR_TRANSCRIPT_STAGE:
        job.transcript_hash = transcript_hash
        job.stage = "queued"
        job.progress_percent = 5
    if transcript_hash != job.transcript_hash:
        mark_summary_generation_failed(
            job,
            error_code="stale_transcript",
            error_message="Transcript changed before summary generation started.",
        )
        return None

    job.status = SummaryGenerationStatus.RUNNING.value
    job.stage = "preparing_transcript"
    job.progress_percent = 10
    job.task_id = task_id or job.task_id
    job.started_at = job.started_at or datetime.now(timezone.utc)
    job.attempt_count += 1

    job.stage = "generating_summary"
    job.progress_percent = 35
    return SummaryGenerationPayload(
        job_id=job.id,
        recording_id=recording.id,
        user_id=user.id,
        transcript=transcript,
        transcript_hash=transcript_hash,
        language=resolve_summary_language_preference(
            user.summary_language,
            recording.language,
            user.default_language,
        ),
        style=resolve_summary_style_preference(user.summary_style),
        instructions=combine_summary_instructions(
            base_instructions=user.summary_instructions,
            personalization_instructions=await summary_personalization_instructions(
                db,
                user_id=user.id,
            ),
            override_instructions=job.instructions_override,
        ),
    )


async def generate_summary_for_payload(payload: SummaryGenerationPayload) -> SummaryResult:
    return await summarize_transcript(
        payload.transcript,
        language=payload.language,
        style=payload.style,
        instructions=payload.instructions,
    )


async def persist_summary_generation_result(
    db: AsyncSession,
    *,
    job_id: UUID,
    summary_result: SummaryResult,
) -> SummaryGenerationJob | None:
    job = await _load_job_for_update(db, job_id)
    if job is None or job.status not in ACTIVE_SUMMARY_GENERATION_STATUSES:
        return job

    job.stage = "saving_summary"
    job.progress_percent = 90

    recording = await _load_recording_for_generation(
        db,
        recording_id=job.recording_id,
        user_id=job.user_id,
        include_outputs=True,
        lock=True,
    )
    if recording is None:
        mark_summary_generation_failed(
            job,
            error_code="recording_not_found",
            error_message="Recording not found.",
        )
        return job

    transcript = build_summary_transcript(recording.segments)
    if summary_transcript_hash(transcript) != job.transcript_hash:
        mark_summary_generation_failed(
            job,
            error_code="stale_transcript",
            error_message="Transcript changed while summary generation was running.",
        )
        return job

    await apply_summary_result(
        db,
        recording=recording,
        summary_result=summary_result,
        enrich_entities=False,
    )
    job.status = SummaryGenerationStatus.SUCCEEDED.value
    job.stage = "complete"
    job.progress_percent = 100
    job.error_code = None
    job.error_message = None
    job.completed_at = datetime.now(timezone.utc)
    job.failed_at = None
    await db.flush()

    # Commit the user-visible summary and terminal job state before slower
    # best-effort entity enrichment so the UI can leave "summarizing" as soon as
    # the summary itself is durable.
    await db.commit()

    try:
        await enrich_recording_entities_from_summary(
            db,
            recording=recording,
            summary_result=summary_result,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort after summary commit.
        await db.rollback()
        logger.warning(
            "entity enrichment failed after summary persisted recording=%s err=%s",
            recording.id,
            exc,
        )
    return job


async def fail_summary_generation_job(
    db: AsyncSession,
    *,
    job_id: UUID,
    error_code: str,
    error_message: str,
) -> SummaryGenerationJob | None:
    job = await _load_job_for_update(db, job_id)
    if job is None:
        return None
    if job.status not in ACTIVE_SUMMARY_GENERATION_STATUSES:
        return job
    mark_summary_generation_failed(job, error_code=error_code, error_message=error_message)
    await db.flush()
    return job


def mark_summary_generation_failed(
    job: SummaryGenerationJob,
    *,
    error_code: str,
    error_message: str,
) -> None:
    job.status = SummaryGenerationStatus.FAILED.value
    job.stage = "failed"
    job.progress_percent = 100
    job.error_code = error_code
    job.error_message = error_message
    job.failed_at = datetime.now(timezone.utc)


async def _load_job_for_update(
    db: AsyncSession,
    job_id: UUID,
) -> SummaryGenerationJob | None:
    result = await db.execute(
        select(SummaryGenerationJob).where(SummaryGenerationJob.id == job_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def _load_recording_for_generation(
    db: AsyncSession,
    *,
    recording_id: UUID,
    user_id: UUID,
    include_outputs: bool,
    lock: bool = False,
) -> Recording | None:
    options = [
        selectinload(Recording.segments).options(
            defer(Segment.embedding),
            selectinload(Segment.person),
        )
    ]
    if include_outputs:
        options.extend(
            [
                selectinload(Recording.summary),
                selectinload(Recording.action_items),
                selectinload(Recording.highlights),
            ]
        )

    statement = (
        select(Recording)
        .where(Recording.id == recording_id, Recording.user_id == user_id)
        .options(*options)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


def _parse_due_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


async def _add_summary_highlights(
    db: AsyncSession,
    *,
    recording: Recording,
    summary_result: SummaryResult,
) -> None:
    raw_highlights = summary_result.highlights or []
    if not raw_highlights:
        return

    segment_dicts = [
        {
            "content": segment.content,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
        }
        for segment in sorted(recording.segments, key=lambda item: item.start_ms or 0)
    ]
    resolved = resolve_highlight_timestamps(raw_highlights, segment_dicts)
    for highlight in resolved:
        category = str(highlight.get("category", "insight")).strip()[:30]
        title = str(highlight.get("title", "")).strip()
        if not title:
            continue
        importance = highlight.get("importance", "medium")
        if importance not in {"high", "medium", "low"}:
            importance = "medium"
        db.add(
            Highlight(
                recording_id=recording.id,
                category=category,
                title=title[:500],
                description=highlight.get("description"),
                speaker=highlight.get("speaker"),
                start_ms=highlight.get("start_ms"),
                end_ms=highlight.get("end_ms"),
                importance=importance,
            )
        )
