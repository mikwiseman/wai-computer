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
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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
        async with get_db_context() as db:
            await fail_summary_generation_job(
                db,
                job_id=job_uuid,
                error_code="summarization_failed",
                error_message="We couldn't generate the summary right now. Please try again.",
            )
        raise

    async with get_db_context() as db:
        await persist_summary_generation_result(
            db,
            job_id=job_uuid,
            summary_result=summary_result,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.summary_generation.generate_recording_summary",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=960,
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


async def _mark_summary_generation_timeout(*, job_id: str) -> None:
    async with get_db_context() as db:
        await fail_summary_generation_job(
            db,
            job_id=UUID(job_id),
            error_code="summary_timeout",
            error_message="Summary generation timed out.",
        )
