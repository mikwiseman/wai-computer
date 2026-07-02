"""Periodic repair of missing semantic segment embeddings."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.config import get_settings
from app.core.embedding_backfill import backfill_missing_segment_embeddings as backfill_core
from app.core.observability import fingerprint_text
from app.core.ops_alerts import notify_ops
from app.core.retry_policy import is_openai_insufficient_quota, is_retryable_exception
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Stay under the 900s soft / 960s hard Celery limits with margin; progress is
# committed per batch, so stopping early loses nothing.
BACKFILL_DEADLINE_SECONDS = 840.0

# One ops alert per quota outage window, deduplicated across worker processes.
# The 2026-06 quota exhaustion ran silently for 5 days (31k Sentry errors) —
# embedding coverage for new recordings degraded and nobody was told.
QUOTA_ALERT_DEDUP_KEY = "ops:openai_embedding_quota_alert"
QUOTA_ALERT_DEDUP_TTL_SECONDS = 21_600


async def _quota_alert_first_in_window() -> bool:
    from app.core.transcription_guard import get_redis

    try:
        return bool(
            await get_redis().set(
                QUOTA_ALERT_DEDUP_KEY,
                "1",
                nx=True,
                ex=QUOTA_ALERT_DEDUP_TTL_SECONDS,
            )
        )
    except Exception as exc:  # noqa: BLE001 - alert loudly when dedup store is down
        logger.warning(
            "embedding quota alert dedup unavailable error_type=%s",
            type(exc).__name__,
        )
        return True


def _alert_quota_exhausted_once() -> None:
    if not asyncio.run(_quota_alert_first_in_window()):
        return
    notify_ops(
        alert_code="openai_embedding_quota_exhausted",
        message=(
            "OpenAI embedding quota exhausted — segment embedding backfill is "
            "failing, so semantic search coverage for new recordings degrades "
            "until the quota recovers. Check platform.openai.com billing."
        ),
        level="error",
    )


async def _backfill_missing_segment_embeddings(
    *,
    user_id: str | None = None,
    batch_size: int | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    settings = get_settings()
    async with get_db_context() as db:
        result = await backfill_core(
            db,
            user_id=UUID(user_id) if user_id else None,
            batch_size=batch_size or settings.embedding_backfill_batch_size,
            limit=limit or settings.embedding_backfill_max_segments_per_run,
            deadline_seconds=BACKFILL_DEADLINE_SECONDS,
        )
    return result.as_dict()


@celery_app.task(
    bind=True,
    name="app.tasks.embedding_backfill.backfill_missing_segment_embeddings",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=960,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def backfill_missing_segment_embeddings(
    self,
    *,
    user_id: str | None = None,
    batch_size: int | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    try:
        logger.info(
            "embedding backfill task started task_id=%s retries=%s user_scoped=%s",
            getattr(self.request, "id", None),
            getattr(self.request, "retries", 0),
            user_id is not None,
        )
        result = asyncio.run(
            _backfill_missing_segment_embeddings(
                user_id=user_id,
                batch_size=batch_size,
                limit=limit,
            )
        )
        logger.info(
            "embedding backfill task finished task_id=%s result=%s",
            getattr(self.request, "id", None),
            result,
        )
        return result
    except Exception as exc:
        if is_openai_insufficient_quota(exc):
            _alert_quota_exhausted_once()
        retry_count = int(getattr(self.request, "retries", 0) or 0)
        if is_retryable_exception(exc) and retry_count < int(self.max_retries or 0):
            logger.warning(
                "embedding backfill task retrying task_id=%s retries=%s error_type=%s "
                "error_fingerprint=%s",
                getattr(self.request, "id", None),
                retry_count,
                type(exc).__name__,
                fingerprint_text(str(exc)),
            )
            raise self.retry(exc=exc)
        raise
