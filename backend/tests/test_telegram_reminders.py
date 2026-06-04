"""Telegram reminder worker tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.telegram_client import TelegramClientError
from app.models.reminder import UserReminder
from app.models.telegram import TelegramAccount
from app.models.user import User
from app.tasks import telegram_reminders as telegram_reminders_module
from app.tasks.telegram_reminders import dispatch_due_telegram_reminders


class _ReminderCapture:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_message(self, chat_id: int, text: str) -> dict[str, int]:
        self.messages.append({"chat_id": chat_id, "text": text})
        return {"message_id": len(self.messages)}


class _ReminderErrorCapture:
    async def send_message(self, chat_id: int, text: str) -> dict[str, int]:
        raise TelegramClientError("blocked")


@pytest.mark.asyncio
async def test_dispatch_due_telegram_reminders_sends_once(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    user = User(email="reminder-worker@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=700, telegram_chat_id=701))
    due = UserReminder(
        user_id=user.id,
        source="telegram",
        text="stand up",
        due_at=now - timedelta(minutes=1),
        status="pending",
    )
    future = UserReminder(
        user_id=user.id,
        source="telegram",
        text="later",
        due_at=now + timedelta(minutes=1),
        status="pending",
    )
    app_surface = UserReminder(
        user_id=user.id,
        source="web",
        text="app-only",
        due_at=now - timedelta(seconds=30),
        status="pending",
    )
    db_session.add_all([due, future, app_surface])
    await db_session.commit()
    capture = _ReminderCapture()

    counts = await dispatch_due_telegram_reminders(
        db_session=db_session,
        client=capture,
        now=now,
    )

    await db_session.refresh(due)
    await db_session.refresh(future)
    await db_session.refresh(app_surface)
    assert counts == {"sent": 2, "failed": 0, "skipped": 0}
    assert due.status == "sent"
    assert due.sent_at == now
    assert due.metadata_["sent_message_id"] == 1
    assert future.status == "pending"
    assert app_surface.status == "sent"
    assert app_surface.sent_at == now
    assert app_surface.metadata_["sent_message_id"] == 2
    assert capture.messages == [
        {"chat_id": 701, "text": "Напоминание: stand up"},
        {"chat_id": 701, "text": "Напоминание: app-only"},
    ]


def test_due_telegram_reminders_query_locks_all_due_pending_reminders() -> None:
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    compiled = str(
        telegram_reminders_module._due_telegram_reminders_query(now, 10).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "WHERE user_reminders.status = " in compiled
    assert "AND user_reminders.source = " not in compiled
    assert "FOR UPDATE SKIP LOCKED" in compiled


@pytest.mark.asyncio
async def test_dispatch_due_telegram_reminders_prefers_original_chat(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    user = User(email="reminder-chat-precedence@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    db_session.add(TelegramAccount(user_id=user.id, telegram_user_id=900, telegram_chat_id=901))
    reminder = UserReminder(
        user_id=user.id,
        source="telegram",
        text="same chat",
        due_at=now - timedelta(minutes=1),
        status="pending",
        telegram_chat_id=777,
    )
    db_session.add(reminder)
    await db_session.commit()
    capture = _ReminderCapture()

    counts = await dispatch_due_telegram_reminders(
        db_session=db_session,
        client=capture,
        now=now,
    )

    await db_session.refresh(reminder)
    assert counts == {"sent": 1, "failed": 0, "skipped": 0}
    assert reminder.status == "sent"
    assert reminder.telegram_chat_id == 777
    assert capture.messages == [{"chat_id": 777, "text": "Напоминание: same chat"}]


@pytest.mark.asyncio
async def test_dispatch_due_telegram_reminders_uses_context_session(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    user = User(email="context-reminder@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    due = UserReminder(
        user_id=user.id,
        source="telegram",
        text="unlinked",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        status="pending",
    )
    db_session.add(due)
    await db_session.commit()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(telegram_reminders_module, "get_db_context", fake_db_context)

    counts = await dispatch_due_telegram_reminders(client=_ReminderCapture())

    await db_session.refresh(due)
    assert counts == {"sent": 0, "failed": 1, "skipped": 0}
    assert due.status == "failed"
    assert due.error == "telegram_not_linked"


@pytest.mark.asyncio
async def test_dispatch_due_telegram_reminders_handles_unavailable_client(
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    user = User(email="reminder-no-client@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()
    due = UserReminder(
        user_id=user.id,
        source="web",
        text="needs Telegram config",
        due_at=now - timedelta(minutes=1),
        status="pending",
    )
    db_session.add(due)
    await db_session.commit()

    class BrokenClient:
        def __init__(self) -> None:
            raise TelegramClientError("Telegram bot token is not configured")

    monkeypatch.setattr(telegram_reminders_module, "TelegramBotClient", BrokenClient)
    counts = await dispatch_due_telegram_reminders(db_session=db_session, now=now)

    await db_session.refresh(due)
    assert counts == {"sent": 0, "failed": 1, "skipped": 0}
    assert due.status == "failed"
    assert due.error == "TelegramClientError"


@pytest.mark.asyncio
async def test_send_one_marks_terminal_failures(db_session: AsyncSession) -> None:
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    skipped = UserReminder(
        user_id=uuid4(),
        source="telegram",
        text="already sent",
        due_at=now,
        status="sent",
    )

    assert (
        await telegram_reminders_module._send_one(
            db_session,
            skipped,
            client=_ReminderCapture(),
            now=now,
        )
        == "skipped"
    )

    orphan = UserReminder(
        user_id=uuid4(),
        source="telegram",
        text="orphan",
        due_at=now,
        status="pending",
    )
    inactive_user = User(
        email="inactive-reminder@example.com",
        password_hash="hash",
        account_status="paused",
    )
    unlinked_user = User(email="unlinked-reminder@example.com", password_hash="hash")
    linked_user = User(email="linked-reminder@example.com", password_hash="hash")
    db_session.add_all([inactive_user, unlinked_user, linked_user])
    await db_session.flush()
    db_session.add(TelegramAccount(user_id=linked_user.id, telegram_user_id=702))
    inactive = UserReminder(
        user_id=inactive_user.id,
        source="telegram",
        text="inactive",
        due_at=now,
        status="pending",
    )
    unlinked = UserReminder(
        user_id=unlinked_user.id,
        source="telegram",
        text="unlinked",
        due_at=now,
        status="pending",
    )
    blocked = UserReminder(
        user_id=linked_user.id,
        source="telegram",
        text="blocked",
        due_at=now,
        status="pending",
    )

    assert (
        await telegram_reminders_module._send_one(
            db_session,
            orphan,
            client=_ReminderCapture(),
            now=now,
        )
        == "failed"
    )
    assert orphan.status == "failed"
    assert orphan.error == "user_not_found"

    assert (
        await telegram_reminders_module._send_one(
            db_session,
            inactive,
            client=_ReminderCapture(),
            now=now,
        )
        == "failed"
    )
    assert inactive.status == "failed"
    assert inactive.failed_at == now
    assert inactive.error == "user_inactive"

    assert (
        await telegram_reminders_module._send_one(
            db_session,
            unlinked,
            client=_ReminderCapture(),
            now=now,
        )
        == "failed"
    )
    assert unlinked.status == "failed"
    assert unlinked.error == "telegram_not_linked"

    assert (
        await telegram_reminders_module._send_one(
            db_session,
            blocked,
            client=_ReminderErrorCapture(),
            now=now,
        )
        == "failed"
    )
    assert blocked.status == "failed"
    assert blocked.error == "TelegramClientError"


def test_dispatch_due_task_delegates_to_asyncio_run(monkeypatch) -> None:
    calls: list[object] = []

    def fake_run(coro):
        calls.append(coro)
        coro.close()
        return {"sent": 2, "failed": 1, "skipped": 0}

    monkeypatch.setattr(telegram_reminders_module.asyncio, "run", fake_run)

    assert telegram_reminders_module.dispatch_due_task(limit=3) == {
        "sent": 2,
        "failed": 1,
        "skipped": 0,
    }
    assert len(calls) == 1
