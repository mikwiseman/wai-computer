"""Celery task for canonical audio-backed recording processing."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded

from app.config import get_settings
from app.core.observability import capture_sentry_anomaly, fingerprint_text
from app.core.recording_audio_processing import (
    delete_staged_file,
    mark_recording_processing_failed,
)
from app.core.recording_audio_processing import (
    process_staged_recording_upload as process_staged_recording_upload_core,
)
from app.core.recording_recovery import mark_stale_processing_recordings
from app.core.retry_policy import is_retryable_exception
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


async def _process_staged_recording_upload(
    *,
    recording_id: str,
    user_id: str,
    staged_path: str,
    content_type: str,
    user_default_language: str | None,
    client_duration_seconds: int | None = None,
    client_file_size_bytes: int | None = None,
    staged_size_bytes: int | None = None,
    previous_failure_code: str | None = None,
) -> None:
    async with get_db_context() as db:
        await process_staged_recording_upload_core(
            db,
            recording_id=UUID(recording_id),
            user_id=UUID(user_id),
            staged_path=Path(staged_path),
            content_type=content_type,
            user_default_language=user_default_language,
            client_duration_seconds=client_duration_seconds,
            client_file_size_bytes=client_file_size_bytes,
            staged_size_bytes=staged_size_bytes,
            previous_failure_code=previous_failure_code,
        )


async def _mark_processing_timeout(*, recording_id: str) -> None:
    async with get_db_context() as db:
        await mark_recording_processing_failed(
            db,
            recording_id=UUID(recording_id),
            failure_code="processing_timeout",
            failure_message="Recording processing timed out.",
        )


async def _recover_stale_recording_processing() -> int:
    stale_after_minutes = settings.recording_processing_stale_after_minutes
    if stale_after_minutes <= 0:
        return 0

    async with get_db_context() as db:
        return await mark_stale_processing_recordings(
            db,
            stale_after=timedelta(minutes=stale_after_minutes),
        )


@celery_app.task(
    name="app.tasks.recording_audio_processing.recover_stale_recording_processing",
    ignore_result=True,
)
def recover_stale_recording_processing() -> int:
    return asyncio.run(_recover_stale_recording_processing())


@celery_app.task(
    bind=True,
    name="app.tasks.recording_audio_processing.process_staged_recording_upload",
    acks_late=True,
    reject_on_worker_lost=True,
    # Long recordings (90+ min) must finish well within these limits, and the
    # hard limit must stay BELOW the broker visibility_timeout (21600s) so a hung
    # task is killed before Redis can redeliver a duplicate. max_retries reduced
    # to bound re-billing on transient failures. (2026-05-31 batch cost incident.)
    soft_time_limit=21000,
    time_limit=21300,
    max_retries=1,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_staged_recording_upload(
    self,
    *,
    recording_id: str,
    user_id: str,
    staged_path: str,
    content_type: str,
    user_default_language: str | None,
    client_duration_seconds: int | None = None,
    client_file_size_bytes: int | None = None,
    staged_size_bytes: int | None = None,
    previous_failure_code: str | None = None,
) -> None:
    try:
        logger.info(
            "recording processing task started recording_id=%s task_id=%s retries=%s",
            recording_id,
            getattr(self.request, "id", None),
            getattr(self.request, "retries", 0),
        )
        asyncio.run(
            _process_staged_recording_upload(
                recording_id=recording_id,
                user_id=user_id,
                staged_path=staged_path,
                content_type=content_type,
                user_default_language=user_default_language,
                client_duration_seconds=client_duration_seconds,
                client_file_size_bytes=client_file_size_bytes,
                staged_size_bytes=staged_size_bytes,
                previous_failure_code=previous_failure_code,
            )
        )
        logger.info(
            "recording processing task finished recording_id=%s task_id=%s",
            recording_id,
            getattr(self.request, "id", None),
        )
    except SoftTimeLimitExceeded:
        retry_count = int(getattr(self.request, "retries", 0) or 0)
        asyncio.run(_mark_processing_timeout(recording_id=recording_id))
        capture_sentry_anomaly(
            "recording.processing.timeout",
            "Recording processing task timed out",
            category="recording",
            extras={
                "recording_id": recording_id,
                "task_id": getattr(self.request, "id", None),
                "retries": retry_count,
                "content_type": content_type,
                "previous_failure_code": previous_failure_code,
            },
            level="error",
        )
        raise
    except Exception as exc:
        retry_count = int(getattr(self.request, "retries", 0) or 0)
        if is_retryable_exception(exc) and retry_count < int(self.max_retries or 0):
            logger.warning(
                "recording processing task retrying recording_id=%s task_id=%s retries=%s "
                "error_type=%s error_fingerprint=%s",
                recording_id,
                getattr(self.request, "id", None),
                retry_count,
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            raise self.retry(exc=exc)
        if is_retryable_exception(exc):
            error_fingerprint = fingerprint_text(str(exc))
            logger.error(
                "recording processing task retries exhausted recording_id=%s task_id=%s "
                "retries=%s error_type=%s error_fingerprint=%s",
                recording_id,
                getattr(self.request, "id", None),
                retry_count,
                type(exc).__name__,
                error_fingerprint,
            )
            capture_sentry_anomaly(
                "recording.processing.retry_exhausted",
                "Recording processing retries exhausted",
                category="recording",
                extras={
                    "recording_id": recording_id,
                    "task_id": getattr(self.request, "id", None),
                    "retries": retry_count,
                    "error_type": type(exc).__name__,
                    "error_fingerprint": error_fingerprint,
                    "content_type": content_type,
                },
                level="error",
            )
            asyncio.run(
                _mark_processing_failed_after_retries(recording_id=recording_id)
            )
            delete_staged_file(Path(staged_path))
        raise


async def _mark_processing_failed_after_retries(*, recording_id: str) -> None:
    async with get_db_context() as db:
        await mark_recording_processing_failed(
            db,
            recording_id=UUID(recording_id),
            failure_code="processing_retry_exhausted",
            failure_message="Recording processing failed after retryable provider errors.",
        )
