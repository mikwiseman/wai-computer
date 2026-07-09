"""Direct tests for the Telegram media-import Celery task wrapper.

The download/import/reply behavior of ``_run`` is covered end-to-end by the
eager-mode tests in ``test_telegram_integration.py``; here we pin the task
wrapper contract (timeout anomaly, failure logging + Sentry, no retries) and
the guard branches of ``_run`` that drop work quietly (account/user/file_id
gone) versus notify the sender.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from app.models.telegram import TelegramAccount
from app.models.user import User
from app.tasks import telegram_media_import


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "account_id": str(uuid4()),
        "user_id": str(uuid4()),
        "message": {"message_id": 1, "chat": {"id": 7}},
        "media": {"kind": "video", "file_id": "file-id", "mime_type": "video/mp4"},
        "status_message_id": 2,
    }
    base.update(overrides)
    return base


def _coro_factory(*, raises: Exception | None = None):
    async def _inner(*args, **kwargs):
        if raises is not None:
            raise raises

    return _inner


def test_task_timeout_captures_anomaly() -> None:
    with (
        patch.object(telegram_media_import, "_run", _coro_factory(raises=SoftTimeLimitExceeded())),
        patch.object(telegram_media_import, "capture_sentry_anomaly") as anomaly,
    ):
        with pytest.raises(SoftTimeLimitExceeded):
            telegram_media_import.import_telegram_media_task(**_kwargs())
    anomaly.assert_called_once()


def test_task_failure_captures_exception_and_raises() -> None:
    with (
        patch.object(
            telegram_media_import, "_run", _coro_factory(raises=ValueError("boom"))
        ),
        patch.object(telegram_media_import, "capture_sentry_exception") as cap,
    ):
        with pytest.raises(ValueError):
            telegram_media_import.import_telegram_media_task(**_kwargs())
    cap.assert_called_once()


def test_task_success_runs_clean() -> None:
    with patch.object(telegram_media_import, "_run", _coro_factory()):
        telegram_media_import.import_telegram_media_task(**_kwargs())


@pytest.mark.asyncio
async def test_run_drops_when_account_or_user_gone(db_session, monkeypatch) -> None:
    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    client = SimpleNamespace(get_file=AsyncMock(side_effect=AssertionError("must not download")))
    monkeypatch.setattr(telegram_media_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(telegram_media_import, "TelegramBotClient", lambda: client)

    # Neither the account nor the user exists — nothing to notify, nothing to do.
    await telegram_media_import._run(**_kwargs())
    client.get_file.assert_not_called()


@pytest.mark.asyncio
async def test_run_drops_on_missing_file_id(db_session, monkeypatch) -> None:
    user = User(email=f"tg-task-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    account = TelegramAccount(user_id=user.id, telegram_user_id=71, telegram_chat_id=71)
    db_session.add(account)
    await db_session.commit()

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    client = SimpleNamespace(get_file=AsyncMock(side_effect=AssertionError("must not download")))
    monkeypatch.setattr(telegram_media_import, "get_db_context", fake_ctx)
    monkeypatch.setattr(telegram_media_import, "TelegramBotClient", lambda: client)

    await telegram_media_import._run(
        **_kwargs(
            account_id=str(account.id),
            user_id=str(user.id),
            media={"kind": "video", "mime_type": "video/mp4"},  # no file_id
        )
    )
    client.get_file.assert_not_called()
