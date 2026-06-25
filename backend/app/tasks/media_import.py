"""Celery task: turn an uploaded media file (audio/video) into a Recording.

``POST /items/upload`` stages an audio/video file to disk and enqueues this
task. We read the staged bytes and run the full recording pipeline (video
normalisation + transcription) via :func:`import_media_as_recording`, then
delete the staged original. Documents (PDF/text) take the synchronous Item
path instead; only media — which needs ffmpeg + Deepgram — comes here.

Staged-file lifecycle: keep it on a *retryable* failure (so the retry can
re-read it); delete it on success or on a permanent failure (bad/corrupt file).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import (
    capture_sentry_anomaly,
    capture_sentry_exception,
    fingerprint_text,
)
from app.core.recording_import import import_media_as_recording
from app.db.session import get_db_context
from app.models.recording import ACTIVE_RECORDING_STATUSES, Recording, RecordingStatus, Segment
from app.models.user import User
from app.tasks.celery_app import celery_app
from app.tasks.retry_policy import is_retryable_exception

logger = logging.getLogger(__name__)


async def _recording_has_segments(recording_id: UUID, db: AsyncSession) -> bool:
    result = await db.execute(
        select(Segment.id).where(Segment.recording_id == recording_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _mark_missing_staged_file(
    db: AsyncSession,
    *,
    recording: Recording,
    content_type: str | None,
) -> None:
    if recording.status not in ACTIVE_RECORDING_STATUSES:
        logger.info(
            "media import: terminal recording missing staged file, skipping "
            "recording_id=%s status=%s",
            recording.id,
            recording.status,
        )
        return
    logger.error("media import staged file missing recording_id=%s", recording.id)
    recording.status = RecordingStatus.FAILED.value
    recording.failure_code = "staged_file_missing"
    recording.failure_message = "Uploaded media file was missing before processing."
    await db.commit()
    capture_sentry_anomaly(
        "recording.media_import.staged_file.missing",
        "Uploaded media staged file was missing before processing",
        category="recording",
        extras={
            "recording_id": str(recording.id),
            "content_type": content_type,
        },
        level="error",
    )


async def _import(
    *,
    user_id: str,
    staged_path: str,
    recording_id: str | None = None,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    language: str | None,
) -> None:
    async with get_db_context() as db:
        user = (
            await db.execute(select(User).where(User.id == UUID(user_id)))
        ).scalar_one_or_none()
        if user is None:
            # Account vanished between upload and processing — nothing to attach to.
            logger.warning("media import: user gone, dropping staged upload")
            return
        recording = None
        if recording_id is not None:
            recording = (
                await db.execute(
                    select(Recording).where(
                        Recording.id == UUID(recording_id),
                        Recording.user_id == user.id,
                        Recording.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if recording is None:
                logger.warning("media import: recording gone, dropping staged upload")
                return
            if recording.status == RecordingStatus.READY.value and await _recording_has_segments(
                recording.id, db
            ):
                logger.info(
                    "media import: recording already ready, skipping redelivery"
                )
                return
        staged_file = Path(staged_path)
        if not staged_file.exists():
            if recording is not None:
                await _mark_missing_staged_file(
                    db,
                    recording=recording,
                    content_type=content_type,
                )
                return
            raise FileNotFoundError(staged_path)
        data = staged_file.read_bytes()
        await import_media_as_recording(
            db=db,
            user=user,
            data=data,
            filename=filename,
            content_type=content_type,
            title=title,
            source_label="upload",
            language=language,
            recording=recording,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.media_import.import_uploaded_media",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=1800,
    time_limit=1860,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def import_uploaded_media_task(
    self,
    *,
    user_id: str,
    staged_path: str,
    recording_id: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    title: str | None = None,
    language: str | None = None,
) -> None:
    try:
        logger.info("media import task started user=%s", user_id)
        asyncio.run(
            _import(
                user_id=user_id,
                recording_id=recording_id,
                staged_path=staged_path,
                filename=filename,
                content_type=content_type,
                title=title,
                language=language,
            )
        )
        Path(staged_path).unlink(missing_ok=True)  # success: drop the staged original
        logger.info("media import task finished user=%s", user_id)
    except SoftTimeLimitExceeded:
        capture_sentry_anomaly(
            "media.import.timeout",
            "Uploaded media processing timed out",
            category="recording",
            extras={"user_id": user_id},
            level="error",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        logger.error(
            "media import task failed user=%s error_type=%s error_fingerprint=%s",
            user_id,
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        retry_count = int(getattr(self.request, "retries", 0) or 0)
        if is_retryable_exception(exc) and retry_count < int(self.max_retries or 0):
            raise self.retry(exc=exc)  # transient: keep the staged file for the retry
        Path(staged_path).unlink(missing_ok=True)  # permanent failure: clean up
        raise
