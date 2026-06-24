"""Celery task for durable recording summary generation."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded

from app.core.observability import (
    capture_sentry_anomaly,
    capture_sentry_exception,
    fingerprint_text,
)
from app.core.summary_generation import (
    fail_summary_generation_job,
    generate_summary_for_payload,
    persist_summary_generation_result,
    prepare_summary_generation_payload,
)
from app.core.summary_generation import (
    recover_missing_summary_generation_jobs as recover_missing_summary_generation_jobs_core,
)
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app
from app.tasks.retry_policy import is_retryable_exception

logger = logging.getLogger(__name__)


def _enqueue_recording_summary_generation(job_id: UUID) -> str:
    result = generate_recording_summary.apply_async(kwargs={"job_id": str(job_id)})
    return str(result.id)


async def _generate_recording_summary(
    *,
    job_id: str,
    task_id: str | None = None,
) -> None:
    job_uuid = UUID(job_id)
    async with get_db_context() as db:
        payload = await prepare_summary_generation_payload(
            db,
            job_id=job_uuid,
            task_id=task_id,
        )

    if payload is None:
        return

    try:
        summary_result = await generate_summary_for_payload(payload)
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        if is_retryable_exception(exc):
            raise
        async with get_db_context() as db:
            await fail_summary_generation_job(
                db,
                job_id=job_uuid,
                error_code="summarization_failed",
                error_message="We couldn't generate the summary right now. Please try again.",
            )
        raise

    try:
        async with get_db_context() as db:
            await persist_summary_generation_result(
                db,
                job_id=job_uuid,
                summary_result=summary_result,
            )
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        if is_retryable_exception(exc):
            raise
        async with get_db_context() as db:
            await fail_summary_generation_job(
                db,
                job_id=job_uuid,
                error_code="summary_persist_failed",
                error_message="Summary generation failed while saving the result.",
            )
        raise


async def _recover_missing_summary_generation_jobs(*, limit: int = 5) -> int:
    async with get_db_context() as db:
        return await recover_missing_summary_generation_jobs_core(
            db,
            enqueue=_enqueue_recording_summary_generation,
            limit=limit,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.summary_generation.generate_recording_summary",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=960,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def generate_recording_summary(self, *, job_id: str) -> None:
    try:
        logger.info(
            "summary generation task started job_id=%s task_id=%s",
            job_id,
            getattr(self.request, "id", None),
        )
        asyncio.run(
            _generate_recording_summary(
                job_id=job_id,
                task_id=getattr(self.request, "id", None),
            )
        )
        logger.info(
            "summary generation task finished job_id=%s task_id=%s",
            job_id,
            getattr(self.request, "id", None),
        )
    except SoftTimeLimitExceeded:
        asyncio.run(_mark_summary_generation_timeout(job_id=job_id))
        capture_sentry_anomaly(
            "recording.summary_generation.timeout",
            "Summary generation task timed out",
            category="recording",
            extras={
                "job_id": job_id,
                "task_id": getattr(self.request, "id", None),
            },
            level="error",
        )
        raise
    except Exception as exc:
        retry_count = int(getattr(self.request, "retries", 0) or 0)
        if is_retryable_exception(exc) and retry_count < int(self.max_retries or 0):
            logger.info(
                (
                    "summary generation task retrying job_id=%s task_id=%s "
                    "retries=%s error_type=%s error_fingerprint=%s"
                ),
                job_id,
                getattr(self.request, "id", None),
                retry_count,
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            raise self.retry(exc=exc)
        if is_retryable_exception(exc):
            asyncio.run(_mark_summary_generation_retry_exhausted(job_id=job_id))
        logger.error(
            (
                "summary generation task failed job_id=%s task_id=%s "
                "error_type=%s error_fingerprint=%s"
            ),
            job_id,
            getattr(self.request, "id", None),
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        raise


@celery_app.task(
    bind=True,
    name="app.tasks.summary_generation.recover_missing_summary_generation_jobs",
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=120,
)
def recover_missing_summary_generation_jobs(self, *, limit: int = 5) -> int:
    recovered = asyncio.run(_recover_missing_summary_generation_jobs(limit=limit))
    logger.info(
        "missing summary generation recovery finished task_id=%s recovered=%s limit=%s",
        getattr(self.request, "id", None),
        recovered,
        limit,
    )
    return recovered


async def _mark_summary_generation_timeout(*, job_id: str) -> None:
    async with get_db_context() as db:
        await fail_summary_generation_job(
            db,
            job_id=UUID(job_id),
            error_code="summary_timeout",
            error_message="Summary generation timed out.",
        )


async def _mark_summary_generation_retry_exhausted(*, job_id: str) -> None:
    async with get_db_context() as db:
        await fail_summary_generation_job(
            db,
            job_id=UUID(job_id),
            error_code="summary_retry_exhausted",
            error_message="Summary generation failed after retryable provider errors.",
        )
