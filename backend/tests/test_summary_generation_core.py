"""Tests for durable summary generation helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.summarizer import SummaryResult
from app.core.summary_generation import (
    WAITING_FOR_TRANSCRIPT_HASH,
    WAITING_FOR_TRANSCRIPT_STAGE,
    SummaryGenerationEnqueueError,
    apply_summary_result,
    build_summary_transcript,
    fail_summary_generation_job,
    is_orphaned_queued_summary_job,
    latest_summary_generation_job,
    load_active_summary_generation_job,
    persist_summary_generation_result,
    prepare_summary_generation_payload,
    recover_missing_summary_generation_jobs,
    resolve_summary_language_preference,
    resolve_summary_style_preference,
    start_recording_summary_generation_job,
    summary_transcript_hash,
)
from app.models.entity import Entity, EntityMention
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


def _summary_result() -> SummaryResult:
    return SummaryResult(
        title="Generated title",
        summary="Generated summary.",
        key_points=["One point"],
        decisions=[{"decision": "Proceed"}],
        action_items=[
            {"task": "Follow up", "owner": "Mik", "due": date(2026, 5, 30), "priority": "high"},
            {"task": "Review notes", "due": "2026-05-31", "priority": "unexpected"},
            {"task": ""},
        ],
        topics=["planning"],
        people_mentioned=["Mik"],
        follow_up_questions=[],
        sentiment="positive",
        highlights=[
            {
                "category": "decision",
                "title": "Proceed with the plan",
                "description": "The team agreed to proceed.",
                "speaker": "Speaker 1",
                "importance": "high",
            },
            {
                "category": "insight",
                "title": "",
                "importance": "low",
            },
            {
                "category": "concern",
                "title": "Budget risk",
                "description": "Budget risk was mentioned.",
                "importance": "invalid",
            },
        ],
    )


async def _user(db: AsyncSession) -> User:
    user = User(
        email=f"summary-{uuid4().hex}@example.com",
        password_hash="hash",
        default_language="ru",
        summary_language="auto",
        summary_style="detailed",
        summary_instructions="Keep decisions explicit.",
    )
    db.add(user)
    await db.flush()
    return user


async def _recording(db: AsyncSession, user: User, *, with_segments: bool = True) -> Recording:
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.READY.value,
        language="multi",
    )
    db.add(recording)
    await db.flush()
    if with_segments:
        db.add_all(
            [
                Segment(
                    recording_id=recording.id,
                    speaker="Speaker 2",
                    content="Budget risk was mentioned.",
                    start_ms=5000,
                    end_ms=8000,
                    confidence=0.9,
                ),
                Segment(
                    recording_id=recording.id,
                    speaker="Speaker 1",
                    content="The team agreed to proceed with the plan.",
                    start_ms=0,
                    end_ms=4000,
                    confidence=0.95,
                ),
            ]
        )
        await db.flush()
    return recording


async def _segments(db: AsyncSession, recording: Recording) -> list[Segment]:
    return (
        await db.execute(
            select(Segment).where(Segment.recording_id == recording.id).order_by(Segment.start_ms)
        )
    ).scalars().all()


def test_summary_generation_pure_helpers() -> None:
    segments = [
        SimpleNamespace(speaker=None, content="Second", start_ms=2000),
        SimpleNamespace(speaker="Alice", content="First", start_ms=0),
    ]

    transcript = build_summary_transcript(segments)

    assert transcript == "Alice: First\nSpeaker: Second"
    assert summary_transcript_hash(transcript) == summary_transcript_hash(transcript)
    assert resolve_summary_language_preference(" EN ", "ru", "ru") == "en"
    assert resolve_summary_language_preference("auto", "multi", " RU ") == "ru"
    assert resolve_summary_language_preference(None, None, "multi") == "auto"
    assert resolve_summary_style_preference(" detailed ") == "detailed"
    assert resolve_summary_style_preference("verbose") == "medium"
    assert latest_summary_generation_job(SimpleNamespace(summary_generation_jobs=[])) is None

    older = SimpleNamespace(created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = SimpleNamespace(created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert latest_summary_generation_job(
        SimpleNamespace(summary_generation_jobs=[older, newer])
    ) is newer


def test_is_orphaned_queued_summary_job_filters_fresh_and_active_jobs() -> None:
    fresh_requested_at = datetime.now(timezone.utc)
    old_requested_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    old_naive_requested_at = old_requested_at.replace(tzinfo=None)

    assert not is_orphaned_queued_summary_job(
        SimpleNamespace(
            status=SummaryGenerationStatus.RUNNING.value,
            task_id=None,
            stage="queued",
            requested_at=old_requested_at,
            created_at=None,
        )
    )
    assert not is_orphaned_queued_summary_job(
        SimpleNamespace(
            status=SummaryGenerationStatus.QUEUED.value,
            task_id="live-task",
            stage="queued",
            requested_at=old_requested_at,
            created_at=None,
        )
    )
    assert not is_orphaned_queued_summary_job(
        SimpleNamespace(
            status=SummaryGenerationStatus.QUEUED.value,
            task_id=None,
            stage=WAITING_FOR_TRANSCRIPT_STAGE,
            requested_at=old_requested_at,
            created_at=None,
        )
    )
    assert not is_orphaned_queued_summary_job(
        SimpleNamespace(
            status=SummaryGenerationStatus.QUEUED.value,
            task_id=None,
            stage="queued",
            requested_at=fresh_requested_at,
            created_at=None,
        )
    )
    assert is_orphaned_queued_summary_job(
        SimpleNamespace(
            status=SummaryGenerationStatus.QUEUED.value,
            task_id=None,
            stage="queued",
            requested_at=old_naive_requested_at,
            created_at=None,
        )
    )
    assert is_orphaned_queued_summary_job(
        SimpleNamespace(
            status=SummaryGenerationStatus.QUEUED.value,
            task_id=None,
            stage="queued",
            requested_at=None,
            created_at=None,
        )
    )


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_enqueues_only_never_started_ready_recordings(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    missing = await _recording(db_session, user)
    summarized = await _recording(db_session, user)
    with_job = await _recording(db_session, user)
    no_segments = await _recording(db_session, user, with_segments=False)
    processing = await _recording(db_session, user)
    processing.status = RecordingStatus.PROCESSING.value
    db_session.add(
        Summary(
            recording_id=summarized.id,
            summary="Already summarized.",
            key_points=[],
            decisions=[],
            topics=[],
            people_mentioned=[],
            sentiment="neutral",
        )
    )
    existing_job_transcript = build_summary_transcript(await _segments(db_session, with_job))
    db_session.add(
        SummaryGenerationJob(
            recording_id=with_job.id,
            user_id=user.id,
            status=SummaryGenerationStatus.FAILED.value,
            stage="failed",
            transcript_hash=summary_transcript_hash(existing_job_transcript),
            error_code="summarization_failed",
            error_message="Existing failure should not be retried by recovery.",
        )
    )
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=1,
    )

    jobs = (
        await db_session.execute(
            select(SummaryGenerationJob).order_by(SummaryGenerationJob.created_at.asc())
        )
    ).scalars().all()
    missing_jobs = [job for job in jobs if job.recording_id == missing.id]

    assert recovered == 1
    assert len(enqueued) == 1
    assert len(missing_jobs) == 1
    assert missing_jobs[0].status == SummaryGenerationStatus.QUEUED.value
    assert missing_jobs[0].task_id == f"celery-{missing_jobs[0].id}"
    assert {job.recording_id for job in jobs} == {with_job.id, missing.id}
    assert no_segments.status == RecordingStatus.READY.value
    assert processing.status == RecordingStatus.PROCESSING.value


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_enqueues_waiting_job_with_segments(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    waiting_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage=WAITING_FOR_TRANSCRIPT_STAGE,
        progress_percent=5,
        transcript_hash=WAITING_FOR_TRANSCRIPT_HASH,
    )
    db_session.add(waiting_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
    )

    await db_session.refresh(waiting_job)
    assert recovered == 1
    assert enqueued == [waiting_job.id]
    assert waiting_job.status == SummaryGenerationStatus.QUEUED.value
    assert waiting_job.stage == "queued"
    assert waiting_job.transcript_hash == summary_transcript_hash(
        build_summary_transcript(await _segments(db_session, recording))
    )
    assert waiting_job.task_id == f"celery-{waiting_job.id}"


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_fails_terminal_waiting_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    ready_recording = await _recording(db_session, user, with_segments=False)
    failed_recording = await _recording(db_session, user, with_segments=False)
    failed_recording.status = RecordingStatus.FAILED.value
    jobs = [
        SummaryGenerationJob(
            recording_id=ready_recording.id,
            user_id=user.id,
            status=SummaryGenerationStatus.QUEUED.value,
            stage=WAITING_FOR_TRANSCRIPT_STAGE,
            progress_percent=5,
            transcript_hash=WAITING_FOR_TRANSCRIPT_HASH,
        ),
        SummaryGenerationJob(
            recording_id=failed_recording.id,
            user_id=user.id,
            status=SummaryGenerationStatus.QUEUED.value,
            stage=WAITING_FOR_TRANSCRIPT_STAGE,
            progress_percent=5,
            transcript_hash=WAITING_FOR_TRANSCRIPT_HASH,
        ),
    ]
    db_session.add_all(jobs)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
    )

    assert recovered == 0
    assert enqueued == []
    for job in jobs:
        await db_session.refresh(job)
        assert job.status == SummaryGenerationStatus.FAILED.value
        assert job.stage == "failed"
        assert job.progress_percent == 100
        assert job.error_code == "no_transcript_segments"
        assert job.failed_at is not None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_enqueues_orphaned_queued_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    orphaned_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
        requested_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(orphaned_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
    )

    await db_session.refresh(orphaned_job)
    assert recovered == 1
    assert enqueued == [orphaned_job.id]
    assert orphaned_job.status == SummaryGenerationStatus.QUEUED.value
    assert orphaned_job.stage == "queued"
    assert orphaned_job.task_id == f"celery-{orphaned_job.id}"


@pytest.mark.asyncio
async def test_start_summary_generation_reenqueues_orphaned_active_queued_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    orphaned_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
        requested_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(orphaned_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    job = await start_recording_summary_generation_job(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
    )

    await db_session.refresh(orphaned_job)
    assert job is orphaned_job
    assert enqueued == [orphaned_job.id]
    assert orphaned_job.status == SummaryGenerationStatus.QUEUED.value
    assert orphaned_job.stage == "queued"
    assert orphaned_job.progress_percent == 5
    assert orphaned_job.task_id == f"celery-{orphaned_job.id}"
    assert orphaned_job.error_code is None
    assert orphaned_job.error_message is None


@pytest.mark.asyncio
async def test_start_summary_generation_keeps_fresh_queued_job_without_task_id(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    fresh_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
    )
    db_session.add(fresh_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    job = await start_recording_summary_generation_job(
        db_session,
        recording_id=recording.id,
        user_id=user.id,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
    )

    await db_session.refresh(fresh_job)
    assert job is fresh_job
    assert enqueued == []
    assert fresh_job.status == SummaryGenerationStatus.QUEUED.value
    assert fresh_job.stage == "queued"
    assert fresh_job.task_id is None


@pytest.mark.asyncio
async def test_start_summary_generation_fails_orphaned_active_job_on_enqueue_error(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    orphaned_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
        requested_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(orphaned_job)
    await db_session.flush()

    def raise_enqueue_error(job_id: UUID) -> str:
        raise RuntimeError("broker unavailable")

    with pytest.raises(SummaryGenerationEnqueueError):
        await start_recording_summary_generation_job(
            db_session,
            recording_id=recording.id,
            user_id=user.id,
            enqueue=raise_enqueue_error,
        )

    await db_session.refresh(orphaned_job)
    assert orphaned_job.status == SummaryGenerationStatus.FAILED.value
    assert orphaned_job.stage == "failed"
    assert orphaned_job.progress_percent == 100
    assert orphaned_job.task_id is None
    assert orphaned_job.error_code == "summary_enqueue_failed"
    assert orphaned_job.failed_at is not None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_fails_stale_orphaned_queued_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    orphaned_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash="stale",
        task_id=None,
    )
    db_session.add(orphaned_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
    )

    await db_session.refresh(orphaned_job)
    assert recovered == 0
    assert enqueued == []
    assert orphaned_job.status == SummaryGenerationStatus.FAILED.value
    assert orphaned_job.error_code == "stale_transcript"


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_fails_orphaned_queued_enqueue_error(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    orphaned_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage="queued",
        progress_percent=5,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
    )
    db_session.add(orphaned_job)
    await db_session.flush()

    def raise_enqueue_error(job_id: UUID) -> str:
        raise RuntimeError("broker unavailable")

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=raise_enqueue_error,
        limit=10,
    )

    await db_session.refresh(orphaned_job)
    assert recovered == 0
    assert orphaned_job.status == SummaryGenerationStatus.FAILED.value
    assert orphaned_job.error_code == "summary_enqueue_failed"


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_reenqueues_failed_enqueue_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    failed_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.FAILED.value,
        stage="failed",
        progress_percent=100,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
        error_code="summary_enqueue_failed",
        error_message="Failed to start summary generation.",
        failed_at=datetime.now(timezone.utc),
    )
    db_session.add(failed_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
    )

    await db_session.refresh(failed_job)
    assert recovered == 1
    assert enqueued == [failed_job.id]
    assert failed_job.status == SummaryGenerationStatus.QUEUED.value
    assert failed_job.stage == "queued"
    assert failed_job.progress_percent == 5
    assert failed_job.task_id == f"celery-{failed_job.id}"
    assert failed_job.error_code is None
    assert failed_job.error_message is None
    assert failed_job.failed_at is None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_reenqueues_stale_running_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    running_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id="lost-worker-task",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=61),
        attempt_count=1,
    )
    db_session.add(running_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
        running_stale_after_minutes=45,
    )

    await db_session.refresh(running_job)
    assert recovered == 1
    assert enqueued == [running_job.id]
    assert running_job.status == SummaryGenerationStatus.QUEUED.value
    assert running_job.stage == "queued"
    assert running_job.progress_percent == 5
    assert running_job.task_id == f"celery-{running_job.id}"
    assert running_job.started_at is None
    assert running_job.error_code is None
    assert running_job.error_message is None
    assert running_job.failed_at is None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_fails_exhausted_stale_running_job(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    running_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id="lost-worker-task",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=61),
        attempt_count=4,
    )
    db_session.add(running_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
        running_stale_after_minutes=45,
    )

    await db_session.refresh(running_job)
    assert recovered == 0
    assert enqueued == []
    assert running_job.status == SummaryGenerationStatus.FAILED.value
    assert running_job.stage == "failed"
    assert running_job.progress_percent == 100
    assert running_job.error_code == "summary_worker_lost"
    assert running_job.failed_at is not None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_fails_stale_running_transcript(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    running_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash="stale",
        task_id="lost-worker-task",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=61),
        attempt_count=1,
    )
    db_session.add(running_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
        running_stale_after_minutes=45,
    )

    await db_session.refresh(running_job)
    assert recovered == 0
    assert enqueued == []
    assert running_job.status == SummaryGenerationStatus.FAILED.value
    assert running_job.stage == "failed"
    assert running_job.error_code == "stale_transcript"


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_fails_stale_running_enqueue_error(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    running_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id="lost-worker-task",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=61),
        attempt_count=1,
    )
    db_session.add(running_job)
    await db_session.flush()

    def raise_enqueue_error(job_id: UUID) -> str:
        raise RuntimeError("broker unavailable")

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=raise_enqueue_error,
        limit=10,
        running_stale_after_minutes=45,
    )

    await db_session.refresh(running_job)
    assert recovered == 0
    assert running_job.status == SummaryGenerationStatus.FAILED.value
    assert running_job.stage == "failed"
    assert running_job.error_code == "summary_enqueue_failed"


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_keeps_fresh_running_job_active(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    running_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id="live-task",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        attempt_count=1,
    )
    db_session.add(running_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
        running_stale_after_minutes=45,
    )

    await db_session.refresh(running_job)
    assert recovered == 0
    assert enqueued == []
    assert running_job.status == SummaryGenerationStatus.RUNNING.value
    assert running_job.stage == "generating_summary"
    assert running_job.task_id == "live-task"
    assert running_job.started_at is not None
    assert running_job.error_code is None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_keeps_failed_enqueue_on_retry_error(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    failed_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.FAILED.value,
        stage="failed",
        progress_percent=100,
        transcript_hash=summary_transcript_hash(
            build_summary_transcript(await _segments(db_session, recording))
        ),
        task_id=None,
        error_code="summary_enqueue_failed",
        error_message="Failed to start summary generation.",
        failed_at=datetime.now(timezone.utc),
    )
    db_session.add(failed_job)
    await db_session.flush()

    def raise_enqueue_error(job_id: UUID) -> str:
        raise RuntimeError("broker still unavailable")

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=raise_enqueue_error,
        limit=10,
    )

    await db_session.refresh(failed_job)
    assert recovered == 0
    assert failed_job.status == SummaryGenerationStatus.FAILED.value
    assert failed_job.stage == "failed"
    assert failed_job.progress_percent == 100
    assert failed_job.error_code == "summary_enqueue_failed"
    assert failed_job.error_message == "Failed to start summary generation."
    assert failed_job.failed_at is not None
    assert failed_job.task_id is None


@pytest.mark.asyncio
async def test_recover_missing_summary_generation_jobs_keeps_stale_failed_enqueue_job_failed(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    failed_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.FAILED.value,
        stage="failed",
        progress_percent=100,
        transcript_hash="stale",
        task_id=None,
        error_code="summary_enqueue_failed",
        error_message="Failed to start summary generation.",
        failed_at=datetime.now(timezone.utc),
    )
    db_session.add(failed_job)
    await db_session.flush()

    enqueued: list[UUID] = []

    recovered = await recover_missing_summary_generation_jobs(
        db_session,
        enqueue=lambda job_id: enqueued.append(job_id) or f"celery-{job_id}",
        limit=10,
    )

    await db_session.refresh(failed_job)
    assert recovered == 0
    assert enqueued == []
    assert failed_job.status == SummaryGenerationStatus.FAILED.value
    assert failed_job.error_code == "stale_transcript"
    assert failed_job.task_id is None


@pytest.mark.asyncio
async def test_apply_and_persist_summary_result_replaces_generated_outputs(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    existing_summary = Summary(
        recording_id=recording.id,
        summary="Old summary",
        key_points=[],
        decisions=[],
        topics=[],
        people_mentioned=[],
        sentiment="neutral",
    )
    db_session.add(existing_summary)
    db_session.add_all(
        [
            ActionItem(recording_id=recording.id, task="Old generated", source="generated"),
            ActionItem(recording_id=recording.id, task="Keep manual", source="manual"),
            Highlight(recording_id=recording.id, category="old", title="Old", importance="low"),
        ]
    )
    transcript = build_summary_transcript(await _segments(db_session, recording))
    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(transcript),
    )
    db_session.add(job)
    await db_session.flush()

    persisted = await persist_summary_generation_result(
        db_session,
        job_id=job.id,
        summary_result=_summary_result(),
    )
    await db_session.flush()

    assert persisted is job
    assert job.status == SummaryGenerationStatus.SUCCEEDED.value
    assert job.stage == "complete"
    assert job.progress_percent == 100
    assert job.completed_at is not None
    assert existing_summary.summary == "Generated summary."

    actions = (
        await db_session.execute(
            select(ActionItem)
            .where(ActionItem.recording_id == recording.id)
            .order_by(ActionItem.task)
        )
    ).scalars().all()
    assert [action.task for action in actions] == ["Follow up", "Keep manual", "Review notes"]
    assert actions[-1].priority == "medium"

    highlights = (
        await db_session.execute(select(Highlight).where(Highlight.recording_id == recording.id))
    ).scalars().all()
    assert {highlight.title for highlight in highlights} == {
        "Proceed with the plan",
        "Budget risk",
    }
    assert {highlight.importance for highlight in highlights} == {"high", "medium"}

    # Phase 2: the recording's people + topics seeded graph entities + mentions.
    entities = (
        await db_session.execute(select(Entity).where(Entity.user_id == user.id))
    ).scalars().all()
    assert {(e.type, e.name) for e in entities} == {
        ("person", "Mik"),
        ("topic", "planning"),
    }
    mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.source_id == recording.id)
        )
    ).scalars().all()
    assert len(mentions) == 2
    assert all(m.source_kind == "recording" for m in mentions)


@pytest.mark.asyncio
async def test_persist_summary_generation_result_commits_visible_summary_before_entity_extraction(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    transcript = build_summary_transcript(await _segments(db_session, recording))
    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(transcript),
    )
    db_session.add(job)
    await db_session.commit()

    observed: list[tuple[str, str, int, str | None] | None] = []
    session_maker = async_sessionmaker(
        db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def observing_extractor(_transcript: str) -> list[dict[str, object]]:
        async with session_maker() as probe:
            row = (
                await probe.execute(
                    select(
                        SummaryGenerationJob.status,
                        SummaryGenerationJob.stage,
                        SummaryGenerationJob.progress_percent,
                        Summary.summary,
                    )
                    .outerjoin(
                        Summary,
                        Summary.recording_id == SummaryGenerationJob.recording_id,
                    )
                    .where(SummaryGenerationJob.id == job.id)
                )
            ).one_or_none()
            observed.append(row._tuple() if row is not None else None)
        return []

    monkeypatch.setattr(
        "app.core.summary_generation.extract_entities",
        observing_extractor,
    )

    persisted = await persist_summary_generation_result(
        db_session,
        job_id=job.id,
        summary_result=_summary_result(),
    )

    assert persisted is job
    assert observed == [
        (
            SummaryGenerationStatus.SUCCEEDED.value,
            "complete",
            100,
            "Generated summary.",
        )
    ]


@pytest.mark.asyncio
async def test_persist_summary_generation_result_keeps_summary_done_when_enrichment_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    transcript = build_summary_transcript(await _segments(db_session, recording))
    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        stage="generating_summary",
        progress_percent=35,
        transcript_hash=summary_transcript_hash(transcript),
    )
    db_session.add(job)
    await db_session.commit()

    async def fail_enrichment(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("entity graph unavailable")

    monkeypatch.setattr(
        "app.core.summary_generation.enrich_recording_entities_from_summary",
        fail_enrichment,
    )

    persisted = await persist_summary_generation_result(
        db_session,
        job_id=job.id,
        summary_result=_summary_result(),
    )

    assert persisted is job

    session_maker = async_sessionmaker(
        db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as probe:
        row = (
            await probe.execute(
                select(
                    SummaryGenerationJob.status,
                    SummaryGenerationJob.stage,
                    SummaryGenerationJob.progress_percent,
                    Summary.summary,
                )
                .join(Summary, Summary.recording_id == SummaryGenerationJob.recording_id)
                .where(SummaryGenerationJob.id == job.id)
            )
        ).one()

    assert row._tuple() == (
        SummaryGenerationStatus.SUCCEEDED.value,
        "complete",
        100,
        "Generated summary.",
    )


@pytest.mark.asyncio
async def test_apply_summary_result_overrides_auto_title(db_session: AsyncSession) -> None:
    """An auto-generated (or empty) title is replaced by the authoritative
    full-transcript summary title."""
    user = await _user(db_session)
    recording = await _recording(db_session, user)  # title=None, flag defaults True
    # apply_summary_result reads these relationships synchronously — eager-load
    # them so the call doesn't lazy-load under the async session.
    await db_session.refresh(recording, ["summary", "segments", "action_items", "highlights"])
    assert recording.title is None
    assert recording.title_auto_generated is True

    await apply_summary_result(
        db_session, recording=recording, summary_result=_summary_result()
    )

    assert recording.title == "Generated title"
    # Still system-owned — a future, better summary may refine it again.
    assert recording.title_auto_generated is True


@pytest.mark.asyncio
async def test_apply_summary_result_keeps_user_renamed_title(db_session: AsyncSession) -> None:
    """A manually renamed title (title_auto_generated=False) is never clobbered."""
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    recording.title = "Интервью о геймификации"
    recording.title_auto_generated = False
    await db_session.flush()
    await db_session.refresh(recording, ["summary", "segments", "action_items", "highlights"])

    await apply_summary_result(
        db_session, recording=recording, summary_result=_summary_result()
    )

    assert recording.title == "Интервью о геймификации"
    assert recording.title_auto_generated is False


@pytest.mark.asyncio
async def test_prepare_summary_generation_payload_success_and_failure_states(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    transcript = build_summary_transcript(await _segments(db_session, recording))
    job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        transcript_hash=summary_transcript_hash(transcript),
    )
    db_session.add(job)
    await db_session.flush()

    assert await load_active_summary_generation_job(
        db_session, recording_id=recording.id, user_id=user.id
    ) is job

    payload = await prepare_summary_generation_payload(
        db_session,
        job_id=job.id,
        task_id="celery-task",
    )

    assert payload is not None
    assert payload.transcript == (
        "Speaker 1: The team agreed to proceed with the plan.\n"
        "Speaker 2: Budget risk was mentioned."
    )
    assert payload.language == "ru"
    assert payload.style == "detailed"
    assert payload.instructions == "Keep decisions explicit."
    assert job.status == SummaryGenerationStatus.RUNNING.value
    assert job.stage == "generating_summary"
    assert job.progress_percent == 35
    assert job.task_id == "celery-task"
    assert job.started_at is not None
    assert job.attempt_count == 1

    no_segments = await _recording(db_session, user, with_segments=False)
    no_segments_job = SummaryGenerationJob(
        recording_id=no_segments.id,
        user_id=user.id,
        transcript_hash=summary_transcript_hash(""),
    )
    waiting_recording = await _recording(db_session, user, with_segments=False)
    waiting_recording.status = RecordingStatus.PROCESSING.value
    waiting_job = SummaryGenerationJob(
        recording_id=waiting_recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.QUEUED.value,
        stage=WAITING_FOR_TRANSCRIPT_STAGE,
        progress_percent=5,
        transcript_hash=WAITING_FOR_TRANSCRIPT_HASH,
    )
    stale_recording = await _recording(db_session, user)
    stale_job = SummaryGenerationJob(
        recording_id=stale_recording.id,
        user_id=user.id,
        transcript_hash="stale",
    )
    db_session.add_all([no_segments_job, waiting_job, stale_job])
    await db_session.flush()

    assert await prepare_summary_generation_payload(db_session, job_id=no_segments_job.id) is None
    assert no_segments_job.error_code == "no_transcript_segments"

    assert await prepare_summary_generation_payload(db_session, job_id=waiting_job.id) is None
    assert waiting_job.status == SummaryGenerationStatus.QUEUED.value
    assert waiting_job.stage == WAITING_FOR_TRANSCRIPT_STAGE
    assert waiting_job.error_code is None

    assert await prepare_summary_generation_payload(db_session, job_id=stale_job.id) is None
    assert stale_job.error_code == "stale_transcript"


@pytest.mark.asyncio
async def test_persist_and_fail_summary_generation_error_paths(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    stale_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.RUNNING.value,
        transcript_hash="stale",
    )
    completed_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.SUCCEEDED.value,
        stage="complete",
        progress_percent=100,
        transcript_hash="already-complete",
    )
    db_session.add_all([stale_job, completed_job])
    await db_session.flush()

    assert await persist_summary_generation_result(
        db_session,
        job_id=uuid4(),
        summary_result=_summary_result(),
    ) is None
    assert await persist_summary_generation_result(
        db_session,
        job_id=completed_job.id,
        summary_result=_summary_result(),
    ) is completed_job

    failed = await persist_summary_generation_result(
        db_session,
        job_id=stale_job.id,
        summary_result=_summary_result(),
    )
    assert failed is stale_job
    assert stale_job.status == SummaryGenerationStatus.FAILED.value
    assert stale_job.error_code == "stale_transcript"

    assert await fail_summary_generation_job(
        db_session,
        job_id=uuid4(),
        error_code="missing",
        error_message="Missing.",
    ) is None
    marked = await fail_summary_generation_job(
        db_session,
        job_id=completed_job.id,
        error_code="manual_failure",
        error_message="Manual failure.",
    )
    assert marked is completed_job
    assert completed_job.status == SummaryGenerationStatus.SUCCEEDED.value
    assert completed_job.stage == "complete"
    assert completed_job.progress_percent == 100
    assert completed_job.error_code is None
    assert completed_job.failed_at is None


@pytest.mark.asyncio
async def test_fail_summary_generation_job_keeps_succeeded_job_terminal(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    recording = await _recording(db_session, user)
    completed_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    completed_job = SummaryGenerationJob(
        recording_id=recording.id,
        user_id=user.id,
        status=SummaryGenerationStatus.SUCCEEDED.value,
        stage="complete",
        progress_percent=100,
        transcript_hash="already-complete",
        completed_at=completed_at,
    )
    db_session.add(completed_job)
    await db_session.flush()

    marked = await fail_summary_generation_job(
        db_session,
        job_id=completed_job.id,
        error_code="late_timeout",
        error_message="Late timeout after the summary was already saved.",
    )

    assert marked is completed_job
    assert completed_job.status == SummaryGenerationStatus.SUCCEEDED.value
    assert completed_job.stage == "complete"
    assert completed_job.progress_percent == 100
    assert completed_job.error_code is None
    assert completed_job.error_message is None
    assert completed_job.completed_at == completed_at
    assert completed_job.failed_at is None


@pytest.mark.asyncio
async def test_summary_generation_task_helpers(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    db_objects = ["prepare-db", "fail-db", "persist-db", "timeout-db"]

    @asynccontextmanager
    async def fake_db_context():
        yield db_objects.pop(0)

    calls: list[tuple[str, object]] = []
    payload = SimpleNamespace(job_id=uuid4(), transcript="text")

    async def fake_prepare(db, *, job_id: UUID, task_id: str | None = None):
        calls.append(("prepare", db))
        assert task_id == "task-1"
        return payload

    async def fake_generate(received_payload):
        calls.append(("generate", received_payload))
        return _summary_result()

    async def fake_persist(db, *, job_id: UUID, summary_result: SummaryResult):
        calls.append(("persist", db))
        assert summary_result.summary == "Generated summary."

    async def fake_fail(db, *, job_id: UUID, error_code: str, error_message: str):
        calls.append((error_code, db))
        assert error_message

    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "prepare_summary_generation_payload", fake_prepare)
    monkeypatch.setattr(task_module, "generate_summary_for_payload", fake_generate)
    monkeypatch.setattr(task_module, "persist_summary_generation_result", fake_persist)
    monkeypatch.setattr(task_module, "fail_summary_generation_job", fake_fail)

    job_id = str(uuid4())
    await task_module._generate_recording_summary(job_id=job_id, task_id="task-1")
    await task_module._mark_summary_generation_timeout(job_id=job_id)

    assert calls == [
        ("prepare", "prepare-db"),
        ("generate", payload),
        ("persist", "fail-db"),
        ("summary_timeout", "persist-db"),
    ]


@pytest.mark.asyncio
async def test_summary_generation_task_marks_summarization_failure(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    db_objects = ["prepare-db", "fail-db"]

    @asynccontextmanager
    async def fake_db_context():
        yield db_objects.pop(0)

    calls: list[tuple[str, object]] = []

    async def fake_prepare(db, **kwargs):
        calls.append(("prepare", db))
        return SimpleNamespace(job_id=uuid4(), transcript="text")

    async def fake_generate(payload):
        raise RuntimeError("llm unavailable")

    async def fake_fail(db, *, job_id: UUID, error_code: str, error_message: str):
        calls.append((error_code, db))
        assert error_message == "We couldn't generate the summary right now. Please try again."

    captured: list[Exception] = []
    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "prepare_summary_generation_payload", fake_prepare)
    monkeypatch.setattr(task_module, "generate_summary_for_payload", fake_generate)
    monkeypatch.setattr(task_module, "fail_summary_generation_job", fake_fail)
    monkeypatch.setattr(task_module, "capture_sentry_exception", captured.append)

    with pytest.raises(RuntimeError, match="llm unavailable"):
        await task_module._generate_recording_summary(job_id=str(uuid4()))

    assert calls == [("prepare", "prepare-db"), ("summarization_failed", "fail-db")]
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_summary_generation_task_marks_persist_failure(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    db_objects = ["prepare-db", "persist-db", "fail-db"]
    job_id = uuid4()

    @asynccontextmanager
    async def fake_db_context():
        yield db_objects.pop(0)

    calls: list[tuple[str, object]] = []
    payload = SimpleNamespace(job_id=job_id, transcript="text")

    async def fake_prepare(db, **kwargs):
        calls.append(("prepare", db))
        return payload

    async def fake_generate(received_payload):
        calls.append(("generate", received_payload))
        return _summary_result()

    async def fake_persist(db, *, job_id: UUID, summary_result: SummaryResult):
        calls.append(("persist", db))
        raise RuntimeError("summary write invariant failed")

    async def fake_fail(db, *, job_id: UUID, error_code: str, error_message: str):
        calls.append((error_code, db))
        assert error_message == "Summary generation failed while saving the result."

    captured: list[Exception] = []
    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "prepare_summary_generation_payload", fake_prepare)
    monkeypatch.setattr(task_module, "generate_summary_for_payload", fake_generate)
    monkeypatch.setattr(task_module, "persist_summary_generation_result", fake_persist)
    monkeypatch.setattr(task_module, "fail_summary_generation_job", fake_fail)
    monkeypatch.setattr(task_module, "capture_sentry_exception", captured.append)

    with pytest.raises(RuntimeError, match="summary write invariant failed"):
        await task_module._generate_recording_summary(job_id=str(job_id))

    assert calls == [
        ("prepare", "prepare-db"),
        ("generate", payload),
        ("persist", "persist-db"),
        ("summary_persist_failed", "fail-db"),
    ]
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_summary_generation_task_leaves_retryable_persist_failure_active(
    monkeypatch,
) -> None:
    from app.tasks import summary_generation as task_module

    db_objects = ["prepare-db", "persist-db", "fail-db"]
    job_id = uuid4()

    @asynccontextmanager
    async def fake_db_context():
        yield db_objects.pop(0)

    payload = SimpleNamespace(job_id=job_id, transcript="text")

    async def fake_prepare(db, **kwargs):
        return payload

    async def fake_generate(received_payload):
        return _summary_result()

    async def fake_persist(db, *, job_id: UUID, summary_result: SummaryResult):
        raise OperationalError(
            "UPDATE summary_generation_jobs",
            {},
            RuntimeError("database unavailable"),
        )

    fail_calls: list[str] = []
    captured: list[Exception] = []

    async def fake_fail(db, **kwargs):
        fail_calls.append(db)

    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "prepare_summary_generation_payload", fake_prepare)
    monkeypatch.setattr(task_module, "generate_summary_for_payload", fake_generate)
    monkeypatch.setattr(task_module, "persist_summary_generation_result", fake_persist)
    monkeypatch.setattr(task_module, "fail_summary_generation_job", fake_fail)
    monkeypatch.setattr(task_module, "capture_sentry_exception", captured.append)

    with pytest.raises(OperationalError):
        await task_module._generate_recording_summary(job_id=str(job_id))

    assert fail_calls == []
    assert len(captured) == 1
    assert db_objects == ["fail-db"]


@pytest.mark.asyncio
async def test_summary_generation_task_leaves_retryable_failure_active(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    db_objects = ["prepare-db", "fail-db"]

    @asynccontextmanager
    async def fake_db_context():
        yield db_objects.pop(0)

    request = httpx.Request("POST", "https://api.cerebras.ai/v1/chat/completions")
    provider_error = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=httpx.Response(429, request=request),
    )

    async def fake_prepare(db, **kwargs):
        return SimpleNamespace(job_id=uuid4(), transcript="text")

    async def fake_generate(payload):
        raise RuntimeError("summarizer wrapped provider error") from provider_error

    fail_calls: list[str] = []

    async def fake_fail(db, **kwargs):
        fail_calls.append(db)

    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "prepare_summary_generation_payload", fake_prepare)
    monkeypatch.setattr(task_module, "generate_summary_for_payload", fake_generate)
    monkeypatch.setattr(task_module, "fail_summary_generation_job", fake_fail)

    with pytest.raises(RuntimeError, match="summarizer wrapped provider error"):
        await task_module._generate_recording_summary(job_id=str(uuid4()))

    assert fail_calls == []


@pytest.mark.asyncio
async def test_summary_generation_task_returns_when_payload_not_available(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    @asynccontextmanager
    async def fake_db_context():
        yield "prepare-db"

    async def fake_prepare(db, **kwargs):
        return None

    async def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("generate should not run without a payload")

    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "prepare_summary_generation_payload", fake_prepare)
    monkeypatch.setattr(task_module, "generate_summary_for_payload", fail_if_called)

    await task_module._generate_recording_summary(job_id=str(uuid4()))


@pytest.mark.asyncio
async def test_summary_generation_recovery_task_helper(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    @asynccontextmanager
    async def fake_db_context():
        yield "recovery-db"

    calls: list[tuple[object, object, int, int]] = []

    async def fake_recover(db, *, enqueue, limit: int, running_stale_after_minutes: int):
        calls.append((db, enqueue, limit, running_stale_after_minutes))
        return 3

    monkeypatch.setattr(task_module, "get_db_context", fake_db_context)
    monkeypatch.setattr(task_module, "recover_missing_summary_generation_jobs_core", fake_recover)

    recovered = await task_module._recover_missing_summary_generation_jobs(limit=7)

    assert recovered == 3
    assert calls == [
        (
            "recovery-db",
            task_module._enqueue_recording_summary_generation,
            7,
            task_module.get_settings().summary_generation_running_stale_after_minutes,
        )
    ]


def test_summary_generation_celery_task_runs_async_helper(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    calls: list[tuple[str, str | None]] = []

    async def fake_generate(*, job_id: str, task_id: str | None = None):
        calls.append((job_id, task_id))

    monkeypatch.setattr(task_module, "_generate_recording_summary", fake_generate)

    job_id = str(uuid4())
    task_module.generate_recording_summary.run(job_id=job_id)

    assert calls == [(job_id, None)]


def test_summary_generation_celery_task_marks_soft_timeout(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    timeouts: list[str] = []
    anomalies: list[tuple[str, dict[str, object]]] = []

    async def fake_generate(*, job_id: str, task_id: str | None = None):
        raise task_module.SoftTimeLimitExceeded()

    async def fake_mark_timeout(*, job_id: str):
        timeouts.append(job_id)

    def fake_capture_sentry_anomaly(name: str, message: str, **kwargs):
        anomalies.append((name, kwargs))

    monkeypatch.setattr(task_module, "_generate_recording_summary", fake_generate)
    monkeypatch.setattr(task_module, "_mark_summary_generation_timeout", fake_mark_timeout)
    monkeypatch.setattr(task_module, "capture_sentry_anomaly", fake_capture_sentry_anomaly)

    job_id = str(uuid4())
    with pytest.raises(task_module.SoftTimeLimitExceeded):
        task_module.generate_recording_summary.run(job_id=job_id)

    assert timeouts == [job_id]
    assert anomalies == [
        (
            "recording.summary_generation.timeout",
            {
                "category": "recording",
                "extras": {"job_id": job_id, "task_id": None},
                "level": "error",
            },
        )
    ]


def test_summary_generation_celery_task_reraises_generic_failure(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    async def fake_generate(*, job_id: str, task_id: str | None = None):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(task_module, "_generate_recording_summary", fake_generate)

    with pytest.raises(RuntimeError, match="database unavailable"):
        task_module.generate_recording_summary.run(job_id=str(uuid4()))


def test_summary_generation_celery_task_retries_retryable_failure(monkeypatch) -> None:
    from app.tasks import summary_generation as task_module

    class RetrySentinelError(Exception):
        pass

    request = httpx.Request("POST", "https://api.cerebras.ai/v1/chat/completions")
    provider_error = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=httpx.Response(429, request=request),
    )

    async def fake_generate(*, job_id: str, task_id: str | None = None):
        raise RuntimeError("summarizer wrapped provider error") from provider_error

    retry_calls: list[Exception] = []

    def fake_retry(*, exc: Exception):
        retry_calls.append(exc)
        raise RetrySentinelError

    monkeypatch.setattr(task_module, "_generate_recording_summary", fake_generate)
    monkeypatch.setattr(task_module.generate_recording_summary, "retry", fake_retry)

    with pytest.raises(RetrySentinelError):
        task_module.generate_recording_summary.run(job_id=str(uuid4()))

    assert len(retry_calls) == 1
