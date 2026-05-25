"""Periodic repair of missing semantic segment embeddings."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.config import get_settings
from app.core.embedding_backfill import backfill_missing_segment_embeddings as backfill_core
from app.core.observability import fingerprint_text
from app.core.retry_policy import is_retryable_exception
from app.db.session import get_db_context
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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
