"""Celery task: process a buffered Telegram photo album as one capture.

The webhook buffers each album part in ``telegram_media_group_parts`` (the API
runs multiple gunicorn workers, so in-process aggregation would split albums)
and schedules this task once per album with a short countdown. The task runs
the combined vision pass and delivers ONE Telegram reply for the whole album.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select

from app.core.observability import capture_sentry_anomaly, capture_sentry_exception
from app.core.telegram_client import TelegramBotClient
from app.db.session import get_db_context
from app.models.telegram import TelegramAccount, TelegramMediaGroupPart
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_PROCESSED_RETENTION = timedelta(days=1)


async def _run(*, media_group_id: str, telegram_user_id: int) -> None:
    # The route helpers own the reply flow; imported lazily so the worker does
    # not pay the FastAPI route module import unless an album actually runs.
    from app.api.routes.telegram import _process_photo_album

    client = TelegramBotClient()
    async with get_db_context() as db:
        account = (
            await db.execute(
                select(TelegramAccount).where(
                    TelegramAccount.telegram_user_id == telegram_user_id
                )
            )
        ).scalar_one_or_none()
        if account is None:
            logger.warning("telegram album import: account gone, dropping")
            return

        parts = list(
            (
                await db.execute(
                    select(TelegramMediaGroupPart)
                    .where(
                        TelegramMediaGroupPart.media_group_id == media_group_id,
                        TelegramMediaGroupPart.processed_at.is_(None),
                    )
                    .order_by(TelegramMediaGroupPart.message_id)
                )
            )
            .scalars()
            .all()
        )
        if not parts:
            logger.info("telegram album import: no unprocessed parts, dropping")
            return

        await _process_photo_album(db, client, account=account, parts=parts)

        # Opportunistic cleanup: processed buffers older than the retention
        # window. Unprocessed strays are kept visible for debugging.
        await db.execute(
            delete(TelegramMediaGroupPart).where(
                TelegramMediaGroupPart.processed_at.is_not(None),
                TelegramMediaGroupPart.created_at
                < datetime.now(timezone.utc) - _PROCESSED_RETENTION,
            )
        )


@celery_app.task(
    bind=True,
    name="app.tasks.telegram_album_import.process_telegram_media_group",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=600,
    time_limit=660,
    # One album = one debounced enqueue; a retry would re-run the vision pass
    # and could double-reply, so failures answer the user instead of retrying.
    max_retries=0,
)
def process_telegram_media_group_task(
    self,
    *,
    media_group_id: str,
    telegram_user_id: int,
) -> None:
    try:
        logger.info("telegram album task started")
        asyncio.run(
            _run(media_group_id=media_group_id, telegram_user_id=telegram_user_id)
        )
        logger.info("telegram album task finished")
    except SoftTimeLimitExceeded:
        capture_sentry_anomaly(
            "telegram.album_import.timeout",
            "Telegram album import timed out",
            category="recording",
            level="error",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        logger.error("telegram album task failed error_type=%s", type(exc).__name__)
        raise
