"""Celery task: build a ComparisonSet's table in the background."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded

from app.core.comparison_build import build_comparison_set
from app.core.observability import (
    capture_sentry_anomaly,
    capture_sentry_exception,
    fingerprint_text,
)
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app
from app.tasks.retry_policy import is_retryable_exception

logger = logging.getLogger(__name__)


async def _generate(*, comparison_id: str, intent: str | None) -> None:
    async with get_db_context() as db:
        await build_comparison_set(db, UUID(comparison_id), intent=intent)


@celery_app.task(
    bind=True,
    name="app.tasks.comparison_generation.generate_comparison",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=600,
    time_limit=660,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def generate_comparison_task(self, *, comparison_id: str, intent: str | None = None) -> None:
    try:
        logger.info("comparison task started id=%s", comparison_id)
        asyncio.run(_generate(comparison_id=comparison_id, intent=intent))
        logger.info("comparison task finished id=%s", comparison_id)
    except SoftTimeLimitExceeded:
        capture_sentry_anomaly(
            "comparison.generation.timeout",
            "Comparison generation timed out",
            category="comparison",
            extras={"comparison_id": comparison_id},
            level="error",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        logger.error(
            "comparison task failed id=%s error_type=%s error_fingerprint=%s",
            comparison_id,
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        retry_count = int(getattr(self.request, "retries", 0) or 0)
        if is_retryable_exception(exc) and retry_count < int(self.max_retries or 0):
            raise self.retry(exc=exc)
        raise
