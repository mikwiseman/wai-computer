"""Dispatch due Telegram reminders."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.telegram_client import TelegramBotClient, TelegramClientError
from app.db.session import get_db_context
from app.models.reminder import UserReminder
from app.models.telegram import TelegramAccount
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_delivery_chat(
    db: AsyncSession, *, user_id: UUID
) -> tuple[User | None, TelegramAccount | None]:
    user = await db.get(User, user_id)
    account = (
        await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user_id))
    ).scalar_one_or_none()
    return user, account


async def _send_one(
    db: AsyncSession,
    reminder: UserReminder,
    *,
    client: TelegramBotClient,
    now: datetime,
) -> str:
    if reminder.status != "pending":
        return "skipped"
    user, account = await _load_delivery_chat(db, user_id=reminder.user_id)
    if user is None:
        reminder.status = "failed"
        reminder.failed_at = now
        reminder.error = "user_not_found"
        return "failed"
    if getattr(user, "account_status", "active") != "active":
        reminder.status = "failed"
        reminder.failed_at = now
        reminder.error = "user_inactive"
        return "failed"
    if account is None or (account.telegram_chat_id is None and account.telegram_user_id is None):
        reminder.status = "failed"
        reminder.failed_at = now
        reminder.error = "telegram_not_linked"
        return "failed"

    chat_id = reminder.telegram_chat_id or account.telegram_chat_id or account.telegram_user_id
    try:
        receipt = await client.send_message(chat_id, f"Напоминание: {reminder.text}")
    except TelegramClientError as exc:
        logger.warning(
            "telegram reminder send failed reminder_id=%s error=%s",
            reminder.id,
            type(exc).__name__,
        )
        reminder.status = "failed"
        reminder.failed_at = now
        reminder.error = type(exc).__name__
        return "failed"

    reminder.status = "sent"
    reminder.sent_at = now
    reminder.telegram_chat_id = chat_id
    if isinstance(receipt, dict) and isinstance(receipt.get("message_id"), int):
        reminder.metadata_ = {
            **(reminder.metadata_ or {}),
            "sent_message_id": receipt["message_id"],
        }
    return "sent"


async def dispatch_due_telegram_reminders(
    *,
    db_session: AsyncSession | None = None,
    client: TelegramBotClient | None = None,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, int]:
    """Send due reminders once and mark terminal delivery state."""
    now = now or _now()
    if db_session is not None:
        return await _dispatch_due_in_session(
            db_session, client=client, limit=limit, now=now
        )
    async with get_db_context() as db:
        return await _dispatch_due_in_session(db, client=client, limit=limit, now=now)


def _due_telegram_reminders_query(now: datetime, limit: int) -> Select[tuple[UserReminder]]:
    return (
        select(UserReminder)
        .where(
            UserReminder.status == "pending",
            UserReminder.due_at <= now,
        )
        .order_by(UserReminder.due_at, UserReminder.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


async def _dispatch_due_in_session(
    db: AsyncSession,
    *,
    client: TelegramBotClient | None,
    limit: int,
    now: datetime,
) -> dict[str, int]:
    rows = list(
        (
            await db.execute(_due_telegram_reminders_query(now, limit))
        )
        .scalars()
        .all()
    )
    counts = {"sent": 0, "failed": 0, "skipped": 0}
    if not rows:
        return counts
    try:
        telegram_client = client or TelegramBotClient()
    except TelegramClientError as exc:
        logger.error(
            "telegram reminder delivery unavailable count=%s error=%s",
            len(rows),
            type(exc).__name__,
        )
        for reminder in rows:
            reminder.status = "failed"
            reminder.failed_at = now
            reminder.error = type(exc).__name__
        await db.flush()
        counts["failed"] = len(rows)
        return counts
    for reminder in rows:
        result = await _send_one(db, reminder, client=telegram_client, now=now)
        counts[result] += 1
    await db.flush()
    return counts


@celery_app.task(name="app.tasks.telegram_reminders.dispatch_due")
def dispatch_due_task(limit: int = 50) -> dict[str, int]:
    return asyncio.run(dispatch_due_telegram_reminders(limit=limit))
