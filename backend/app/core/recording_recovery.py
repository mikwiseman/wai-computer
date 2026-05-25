"""Recovery helpers for recordings interrupted by worker restarts or OOM kills."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Recording, RecordingStatus

INTERRUPTED_PROCESSING_FAILURE_CODE = "processing_interrupted"
INTERRUPTED_PROCESSING_FAILURE_MESSAGE = (
    "Обработка была прервана. Импортируй файл ещё раз."
)


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
            failure_message=INTERRUPTED_PROCESSING_FAILURE_MESSAGE,
        )
    )
    await db.commit()
    return int(result.rowcount or 0)
