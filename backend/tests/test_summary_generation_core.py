"""Tests for durable summary generation helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.summarizer import SummaryResult
from app.core.summary_generation import (
    build_summary_transcript,
    fail_summary_generation_job,
    latest_summary_generation_job,
    load_active_summary_generation_job,
    persist_summary_generation_result,
    prepare_summary_generation_payload,
    resolve_summary_language_preference,
    resolve_summary_style_preference,
    summary_transcript_hash,
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
    stale_recording = await _recording(db_session, user)
    stale_job = SummaryGenerationJob(
        recording_id=stale_recording.id,
        user_id=user.id,
        transcript_hash="stale",
    )
    db_session.add_all([no_segments_job, stale_job])
    await db_session.flush()

    assert await prepare_summary_generation_payload(db_session, job_id=no_segments_job.id) is None
    assert no_segments_job.error_code == "no_transcript_segments"

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
    assert completed_job.status == SummaryGenerationStatus.FAILED.value
    assert completed_job.stage == "failed"
    assert completed_job.progress_percent == 100
    assert completed_job.failed_at is not None


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
