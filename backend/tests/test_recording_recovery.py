from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recording_recovery import (
    ABANDONED_UPLOAD_FAILURE_CODE,
    INTERRUPTED_PROCESSING_FAILURE_CODE,
    mark_abandoned_pending_upload_recordings,
    mark_stale_pending_upload_recordings,
    mark_stale_processing_recordings,
)
from app.models.recording import Recording, RecordingStatus, Segment
from app.models.user import User


@pytest.mark.asyncio
async def test_mark_stale_processing_recordings_fails_only_orphaned_rows(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[dict] = []
    monkeypatch.setattr(
        "app.core.recording_recovery.capture_sentry_message",
        lambda _message, *, level, extras: alerts.append({"level": level, "extras": extras}),
    )
    user = User(email="recovery@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    stale = Recording(
        user_id=user.id,
        title="stale",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=now - timedelta(minutes=20),
    )
    active = Recording(
        user_id=user.id,
        title="active",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        uploaded_at=now - timedelta(minutes=2),
    )
    stale_uploading = Recording(
        user_id=user.id,
        title="stale-uploading",
        type="meeting",
        status=RecordingStatus.UPLOADING.value,
        uploaded_at=now - timedelta(minutes=25),
    )
    ready = Recording(
        user_id=user.id,
        title="ready",
        type="meeting",
        status=RecordingStatus.READY.value,
        uploaded_at=now - timedelta(minutes=30),
    )
    db_session.add_all([stale, active, stale_uploading, ready])
    await db_session.commit()

    count = await mark_stale_processing_recordings(
        db_session,
        stale_after=timedelta(minutes=15),
        now=now,
    )

    assert count == 2
    rows = (await db_session.execute(select(Recording))).scalars().all()
    by_title = {row.title: row for row in rows}
    assert by_title["stale"].status == RecordingStatus.FAILED.value
    assert by_title["stale"].failure_code == INTERRUPTED_PROCESSING_FAILURE_CODE
    assert by_title["stale-uploading"].status == RecordingStatus.FAILED.value
    assert by_title["stale-uploading"].failure_code == INTERRUPTED_PROCESSING_FAILURE_CODE
    assert by_title["active"].status == RecordingStatus.PROCESSING.value
    assert by_title["ready"].status == RecordingStatus.READY.value
    assert alerts == [
        {
            "level": "warning",
            "extras": {
                "alert_code": "recording.processing.stuck",
                "count": 2,
                "stale_after_seconds": 900,
            },
        }
    ]


def test_interrupted_failure_message_localizes_ru_and_en():
    from app.core.recording_recovery import (
        INTERRUPTED_PROCESSING_FAILURE_MESSAGES,
        _interrupted_failure_message,
    )

    assert _interrupted_failure_message("ru") == INTERRUPTED_PROCESSING_FAILURE_MESSAGES["ru"]
    assert _interrupted_failure_message("RU-foo") == INTERRUPTED_PROCESSING_FAILURE_MESSAGES["ru"]
    assert _interrupted_failure_message("en") == INTERRUPTED_PROCESSING_FAILURE_MESSAGES["en"]
    assert _interrupted_failure_message(None) == INTERRUPTED_PROCESSING_FAILURE_MESSAGES["en"]
    assert _interrupted_failure_message("") == INTERRUPTED_PROCESSING_FAILURE_MESSAGES["en"]


@pytest.mark.asyncio
async def test_mark_abandoned_pending_upload_recordings_fails_duplicate_orphan(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[dict] = []
    monkeypatch.setattr(
        "app.core.recording_recovery.capture_sentry_message",
        lambda _message, *, level, extras: alerts.append({"level": level, "extras": extras}),
    )
    user = User(email="pending-duplicate@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    now = datetime(2026, 6, 22, 12, 30, tzinfo=timezone.utc)
    orphan = Recording(
        user_id=user.id,
        title="orphan",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        created_at=now - timedelta(minutes=27),
        updated_at=now - timedelta(minutes=27),
    )
    successor = Recording(
        user_id=user.id,
        title="real recording",
        type="meeting",
        status=RecordingStatus.READY.value,
        uploaded_at=now - timedelta(minutes=5),
        created_at=now - timedelta(minutes=26, seconds=45),
        updated_at=now - timedelta(minutes=1),
    )
    db_session.add_all([orphan, successor])
    await db_session.commit()

    count = await mark_abandoned_pending_upload_recordings(
        db_session,
        abandoned_after=timedelta(minutes=15),
        duplicate_window=timedelta(minutes=5),
        now=now,
    )

    assert count == 1
    rows = (await db_session.execute(select(Recording))).scalars().all()
    by_title = {row.title: row for row in rows}
    assert by_title["orphan"].status == RecordingStatus.FAILED.value
    assert by_title["orphan"].failure_code == ABANDONED_UPLOAD_FAILURE_CODE
    assert by_title["real recording"].status == RecordingStatus.READY.value
    assert alerts == [
        {
            "level": "warning",
            "extras": {
                "alert_code": "recording.upload.abandoned",
                "count": 1,
                "abandoned_after_seconds": 900,
                "duplicate_window_seconds": 300,
            },
        }
    ]


@pytest.mark.asyncio
async def test_mark_abandoned_pending_upload_recordings_preserves_active_and_non_empty_rows(
    db_session: AsyncSession,
) -> None:
    user = User(email="pending-active@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    now = datetime(2026, 6, 22, 12, 30, tzinfo=timezone.utc)
    active_without_successor = Recording(
        user_id=user.id,
        title="active",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        created_at=now - timedelta(minutes=27),
        updated_at=now - timedelta(minutes=27),
    )
    non_empty = Recording(
        user_id=user.id,
        title="non-empty",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        created_at=now - timedelta(minutes=27),
        updated_at=now - timedelta(minutes=27),
    )
    successor = Recording(
        user_id=user.id,
        title="later",
        type="meeting",
        status=RecordingStatus.PROCESSING.value,
        created_at=now - timedelta(minutes=26, seconds=45),
        updated_at=now - timedelta(minutes=26, seconds=45),
    )
    db_session.add_all([active_without_successor, non_empty, successor])
    await db_session.flush()
    db_session.add(
        Segment(
            recording_id=non_empty.id,
            speaker="Speaker 1",
            content="already has transcript",
            start_ms=0,
            end_ms=1000,
        )
    )
    await db_session.commit()

    count = await mark_abandoned_pending_upload_recordings(
        db_session,
        abandoned_after=timedelta(minutes=15),
        duplicate_window=timedelta(seconds=10),
        now=now,
    )

    assert count == 0
    rows = (await db_session.execute(select(Recording))).scalars().all()
    assert {row.title: row.status for row in rows} == {
        "active": RecordingStatus.PENDING_UPLOAD.value,
        "non-empty": RecordingStatus.PENDING_UPLOAD.value,
        "later": RecordingStatus.PROCESSING.value,
    }


@pytest.mark.asyncio
async def test_mark_stale_pending_upload_recordings_fails_only_old_empty_rows(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alerts: list[dict] = []
    monkeypatch.setattr(
        "app.core.recording_recovery.capture_sentry_message",
        lambda _message, *, level, extras: alerts.append({"level": level, "extras": extras}),
    )
    user = User(email="pending-stale@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    stale_empty = Recording(
        user_id=user.id,
        title="stale-empty",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        language="ru",
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=8),
    )
    recent_empty = Recording(
        user_id=user.id,
        title="recent-empty",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    stale_uploaded = Recording(
        user_id=user.id,
        title="stale-uploaded",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        uploaded_at=now - timedelta(days=8),
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=8),
    )
    stale_audio_url = Recording(
        user_id=user.id,
        title="stale-audio-url",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        audio_url="https://example.com/audio.m4a",
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=8),
    )
    stale_with_segment = Recording(
        user_id=user.id,
        title="stale-with-segment",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=8),
    )
    ready = Recording(
        user_id=user.id,
        title="ready",
        type="meeting",
        status=RecordingStatus.READY.value,
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=8),
    )
    db_session.add_all(
        [
            stale_empty,
            recent_empty,
            stale_uploaded,
            stale_audio_url,
            stale_with_segment,
            ready,
        ]
    )
    await db_session.flush()
    db_session.add(
        Segment(
            recording_id=stale_with_segment.id,
            speaker="Speaker 1",
            content="kept",
            start_ms=0,
            end_ms=1000,
        )
    )
    await db_session.commit()

    count = await mark_stale_pending_upload_recordings(
        db_session,
        stale_after=timedelta(days=7),
        now=now,
    )

    assert count == 1
    rows = (await db_session.execute(select(Recording))).scalars().all()
    by_title = {row.title: row for row in rows}
    assert by_title["stale-empty"].status == RecordingStatus.FAILED.value
    assert by_title["stale-empty"].failure_code == ABANDONED_UPLOAD_FAILURE_CODE
    assert by_title["stale-empty"].failure_message == (
        "Запись была начата, но аудио не загрузилось. "
        "Если локальная копия сохранилась, она сможет повторить загрузку."
    )
    assert by_title["recent-empty"].status == RecordingStatus.PENDING_UPLOAD.value
    assert by_title["stale-uploaded"].status == RecordingStatus.PENDING_UPLOAD.value
    assert by_title["stale-audio-url"].status == RecordingStatus.PENDING_UPLOAD.value
    assert by_title["stale-with-segment"].status == RecordingStatus.PENDING_UPLOAD.value
    assert by_title["ready"].status == RecordingStatus.READY.value
    assert alerts == [
        {
            "level": "warning",
            "extras": {
                "alert_code": "recording.upload.stale_abandoned",
                "count": 1,
                "stale_after_seconds": 604800,
            },
        }
    ]


@pytest.mark.asyncio
async def test_mark_stale_pending_upload_recordings_ignores_disabled_cutoff(
    db_session: AsyncSession,
) -> None:
    user = User(email="pending-stale-disabled@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    stale_empty = Recording(
        user_id=user.id,
        title="stale-empty",
        type="meeting",
        status=RecordingStatus.PENDING_UPLOAD.value,
        created_at=now - timedelta(days=8),
        updated_at=now - timedelta(days=8),
    )
    db_session.add(stale_empty)
    await db_session.commit()

    count = await mark_stale_pending_upload_recordings(
        db_session,
        stale_after=timedelta(seconds=0),
        now=now,
    )

    assert count == 0
    row = await db_session.get(Recording, stale_empty.id)
    assert row is not None
    assert row.status == RecordingStatus.PENDING_UPLOAD.value


def test_stale_cutoff_stays_above_recording_task_hard_limit():
    """The reclaim cutoff must exceed the recording transcription task's hard
    time_limit (21300s; see app/tasks/recording_audio_processing.py). Otherwise
    the startup + every-minute recovery sweep force-fails an in-flight or queued
    transcription — e.g. an API restart on deploy killing a live ~5.9h job.
    """
    from app.config import get_settings

    cutoff_seconds = get_settings().recording_processing_stale_after_minutes * 60
    assert cutoff_seconds > 21300
