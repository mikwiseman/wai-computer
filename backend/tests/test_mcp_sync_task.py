"""Tests for the MCP sync dispatch logic (due-connection enqueue)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.mcp_connection import McpConnection
from app.models.user import User
from app.tasks import mcp_sync

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    u = User(email=f"disp-{uuid4().hex}@example.com", password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def test_dispatch_enqueues_due_and_advances_next_sync(db_session, monkeypatch) -> None:
    user = await _user(db_session)
    now = datetime.now(timezone.utc)
    # Due (next_sync_at in the past), never-synced (null), and not-due (future).
    due = McpConnection(
        user_id=user.id, server_label="due", server_url="https://a/mcp",
        enabled=True, next_sync_at=now - timedelta(minutes=1), sync_interval_minutes=60,
    )
    never = McpConnection(
        user_id=user.id, server_label="never", server_url="https://b/mcp",
        enabled=True, next_sync_at=None, sync_interval_minutes=30,
    )
    future = McpConnection(
        user_id=user.id, server_label="future", server_url="https://c/mcp",
        enabled=True, next_sync_at=now + timedelta(hours=1), sync_interval_minutes=60,
    )
    disabled = McpConnection(
        user_id=user.id, server_label="off", server_url="https://d/mcp",
        enabled=False, next_sync_at=now - timedelta(minutes=5),
    )
    db_session.add_all([due, never, future, disabled])
    await db_session.flush()

    # _dispatch_due opens its own session via get_db_context; point it at our test db.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_ctx():
        yield db_session

    enqueued_ids = []
    monkeypatch.setattr(mcp_sync, "get_db_context", fake_ctx)
    with patch.object(mcp_sync.sync_mcp_connection, "delay",
                      side_effect=lambda **kw: enqueued_ids.append(kw["connection_id"])):
        count = await mcp_sync._dispatch_due()

    assert count == 2  # due + never, not future/disabled
    assert str(due.id) in enqueued_ids
    assert str(never.id) in enqueued_ids
    assert str(future.id) not in enqueued_ids
    assert str(disabled.id) not in enqueued_ids
    # next_sync_at advanced for the dispatched ones.
    refreshed = (
        await db_session.execute(select(McpConnection).where(McpConnection.id == due.id))
    ).scalar_one()
    assert refreshed.next_sync_at > now
