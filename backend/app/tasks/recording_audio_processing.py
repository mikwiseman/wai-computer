"""Celery task for canonical audio-backed recording processing."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded

from app.core.observability import fingerprint_text
from app.core.recording_audio_processing import (
    delete_staged_file,
    mark_recording_processing_failed,
)
from app.core.recording_audio_processing import (
    process_staged_recording_upload as process_staged_recording_upload_core,
)
from app.core.retry_policy import is_retryable_exception
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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
        )


async def _mark_processing_timeout(*, recording_id: str) -> None:
    async with get_db_context() as db:
        await mark_recording_processing_failed(
            db,
            recording_id=UUID(recording_id),
            failure_code="processing_timeout",
            failure_message="Recording processing timed out.",
        )


@celery_app.task(
    bind=True,
    name="app.tasks.recording_audio_processing.process_staged_recording_upload",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=3000,
    time_limit=3300,
    max_retries=3,
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
            )
        )
        logger.info(
            "recording processing task finished recording_id=%s task_id=%s",
            recording_id,
            getattr(self.request, "id", None),
        )
    except SoftTimeLimitExceeded:
        asyncio.run(_mark_processing_timeout(recording_id=recording_id))
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
            logger.error(
                "recording processing task retries exhausted recording_id=%s task_id=%s "
                "retries=%s error_type=%s error_fingerprint=%s",
                recording_id,
                getattr(self.request, "id", None),
                retry_count,
                type(exc).__name__,
                fingerprint_text(str(exc)),
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
