"""Celery task: generate an Item's summary + key-moments table off the request path.

Signal-capture-first: ``POST /items`` stores the raw item immediately and
enqueues this task, so the user gets an instant ack and the (slower) LLM work
happens in the background — mirroring how recording summaries are generated.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.core.item_summary import generate_item_summary
from app.core.observability import (
    capture_sentry_anomaly,
    capture_sentry_exception,
    fingerprint_text,
)
from app.db.session import get_db_context
from app.models.item import Item
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _generate_item_summary(*, item_id: str) -> None:
    item_uuid = UUID(item_id)
    async with get_db_context() as db:
        item = (
            await db.execute(select(Item).where(Item.id == item_uuid))
        ).scalar_one_or_none()
        if item is None:
            logger.info("item summary skip — item not found id=%s", item_id)
            return
        if not (item.body or "").strip():
            logger.info("item summary skip — no body id=%s", item_id)
            return
        await generate_item_summary(db, item)


@celery_app.task(
    bind=True,
    name="app.tasks.item_summary_generation.generate_item_summary",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=960,
)
def generate_item_summary_task(self, *, item_id: str) -> None:
    try:
        logger.info("item summary task started item_id=%s", item_id)
        asyncio.run(_generate_item_summary(item_id=item_id))
        logger.info("item summary task finished item_id=%s", item_id)
    except SoftTimeLimitExceeded:
        capture_sentry_anomaly(
            "item.summary_generation.timeout",
            "Item summary generation timed out",
            category="item",
            extras={"item_id": item_id},
            level="error",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        logger.error(
            "item summary task failed item_id=%s error_type=%s error_fingerprint=%s",
            item_id,
            type(exc).__name__,
            fingerprint_text(str(exc)),
        )
        raise
