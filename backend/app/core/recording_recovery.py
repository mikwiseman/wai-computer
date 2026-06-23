"""Recovery helpers for recordings interrupted by worker restarts or OOM kills."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import capture_sentry_message
from app.models.recording import Recording, RecordingStatus, Segment

INTERRUPTED_PROCESSING_FAILURE_CODE = "processing_interrupted"
ABANDONED_UPLOAD_FAILURE_CODE = "upload_abandoned"

INTERRUPTED_PROCESSING_FAILURE_MESSAGES = {
    "en": "Processing was interrupted. Please re-import the file.",
    "ru": "Обработка была прервана. Импортируй файл ещё раз.",
}

ABANDONED_UPLOAD_FAILURE_MESSAGES = {
    "en": (
        "Recording was started, but no audio upload was received. "
        "If a local recovery copy still exists, it can retry the upload."
    ),
    "ru": (
        "Запись была начата, но аудио не загрузилось. "
        "Если локальная копия сохранилась, она сможет повторить загрузку."
    ),
}


def _interrupted_failure_message(language: str | None) -> str:
    normalized = (language or "").strip().lower()
    if normalized.startswith("ru"):
        return INTERRUPTED_PROCESSING_FAILURE_MESSAGES["ru"]
    return INTERRUPTED_PROCESSING_FAILURE_MESSAGES["en"]


def _abandoned_upload_failure_message(language: str | None) -> str:
    normalized = (language or "").strip().lower()
    if normalized.startswith("ru"):
        return ABANDONED_UPLOAD_FAILURE_MESSAGES["ru"]
    return ABANDONED_UPLOAD_FAILURE_MESSAGES["en"]


async def mark_stale_processing_recordings(
    db: AsyncSession,
    *,
    stale_after: timedelta,
    now: datetime | None = None,
) -> int:
    """Mark orphaned processing records as failed after the process has restarted.

    A SIGKILL/OOM cannot run Python cleanup handlers. On the next startup we
    make those records explicit failures instead of leaving the UI in
    `processing` forever.
    """
    effective_now = now or datetime.now(timezone.utc)
    cutoff = effective_now - stale_after
    result = await db.execute(
        update(Recording)
        .where(
            Recording.status.in_(
                [
                    RecordingStatus.UPLOADING.value,
                    RecordingStatus.PROCESSING.value,
                ]
            ),
            Recording.uploaded_at.is_not(None),
            Recording.uploaded_at < cutoff,
        )
        .values(
            status=RecordingStatus.FAILED.value,
            failure_code=INTERRUPTED_PROCESSING_FAILURE_CODE,
            failure_message=INTERRUPTED_PROCESSING_FAILURE_MESSAGES["en"],
        )
    )
    await db.commit()
    count = int(result.rowcount or 0)
    if count:
        capture_sentry_message(
            "Stale recording processing rows marked failed",
            level="warning",
            extras={
                "alert_code": "recording.processing.stuck",
                "count": count,
                "stale_after_seconds": int(stale_after.total_seconds()),
            },
        )
    return count


async def mark_abandoned_pending_upload_recordings(
    db: AsyncSession,
    *,
    abandoned_after: timedelta,
    duplicate_window: timedelta,
    now: datetime | None = None,
) -> int:
    """Fail pre-upload rows that are proven abandoned by a near-duplicate start.

    A live recording can legitimately stay ``pending_upload`` until the user
    stops a long meeting, so this does not use age alone. It only repairs rows
    that never uploaded audio, have no transcript segments, and were followed by
    a newer same-type recording from the same user inside ``duplicate_window``.
    """
    if abandoned_after.total_seconds() <= 0 or duplicate_window.total_seconds() <= 0:
        return 0

    effective_now = now or datetime.now(timezone.utc)
    cutoff = effective_now - abandoned_after
    result = await db.execute(
        select(Recording).where(
            Recording.status == RecordingStatus.PENDING_UPLOAD.value,
            Recording.deleted_at.is_(None),
            Recording.uploaded_at.is_(None),
            Recording.audio_url.is_(None),
            Recording.created_at < cutoff,
            ~exists().where(Segment.recording_id == Recording.id),
        )
    )
    candidates = list(result.scalars().all())
    marked_count = 0
    for recording in candidates:
        duplicate_deadline = recording.created_at + duplicate_window
        duplicate_result = await db.execute(
            select(Recording.id)
            .where(
                Recording.id != recording.id,
                Recording.user_id == recording.user_id,
                Recording.type == recording.type,
                Recording.deleted_at.is_(None),
                Recording.created_at > recording.created_at,
                Recording.created_at <= duplicate_deadline,
            )
            .limit(1)
        )
        if duplicate_result.scalar_one_or_none() is None:
            continue

        recording.status = RecordingStatus.FAILED.value
        recording.failure_code = ABANDONED_UPLOAD_FAILURE_CODE
        recording.failure_message = _abandoned_upload_failure_message(recording.language)
        marked_count += 1

    if not marked_count:
        return 0

    await db.commit()
    capture_sentry_message(
        "Abandoned pending upload recordings marked failed",
        level="warning",
        extras={
            "alert_code": "recording.upload.abandoned",
            "count": marked_count,
            "abandoned_after_seconds": int(abandoned_after.total_seconds()),
            "duplicate_window_seconds": int(duplicate_window.total_seconds()),
        },
    )
    return marked_count
