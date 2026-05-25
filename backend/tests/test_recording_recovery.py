from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recording_recovery import (
    INTERRUPTED_PROCESSING_FAILURE_CODE,
    mark_stale_processing_recordings,
)
from app.models.recording import Recording, RecordingStatus
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
