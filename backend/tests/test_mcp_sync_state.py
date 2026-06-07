"""Tests for the MCP sync state machine, kill-switch guard, and dispatcher filter."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import transcription_guard
from app.core.mcp_client import McpResource
from app.core.mcp_ingest import sync_connection
from app.models.item import Item
from app.models.mcp_connection import McpConnection, McpIngestionRun
from app.models.user import User
from app.tasks.mcp_sync import due_connections_query

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


async def _run(db, conn, client):
    return await sync_connection(db, conn, client_factory=lambda u, t: client, embedder=_embedder)


async def _user(db) -> User:
    u = User(email=f"st-{uuid4().hex}@example.com", password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def _conn(db, user, **kw) -> McpConnection:
    c = McpConnection(
        user_id=user.id, server_label="S",
        server_url=f"https://mcp.example.com/{uuid4().hex}",
        auth_type="none", privacy_level="internal", enabled=True,
    )
    for k, v in kw.items():
        setattr(c, k, v)
    db.add(c)
    await db.flush()
    return c


class _Boom:
    def __init__(self, message="server exploded"):
        self._m = message

    async def list_resources(self):
        raise RuntimeError(self._m)


class _Resource:
    async def list_resources(self):
        return [McpResource(uri="n://1", name="N")]

    async def read_resource(self, uri):
        return "body"


# ── transient error stays eligible, then a success resets it ────────────────
async def test_transient_failure_then_success_resets(db_session):
    user = await _user(db_session)
    conn = await _conn(db_session, user)
    with pytest.raises(RuntimeError):
        await _run(db_session, conn, _Boom())
    assert conn.status == "error_transient"
    assert conn.consecutive_failures == 1
    assert conn.next_sync_at is not None  # eligible for retry

    res = await _run(db_session, conn, _Resource())
    assert res.status == "succeeded"
    assert conn.status == "active"
    assert conn.consecutive_failures == 0
    assert conn.last_success_at is not None


# ── auth error is terminal (stop + reconnect) ───────────────────────────────
async def test_auth_error_is_terminal(db_session):
    user = await _user(db_session)
    conn = await _conn(db_session, user)
    with pytest.raises(RuntimeError):
        await sync_connection(
            db_session, conn,
            client_factory=lambda u, t: _Boom("HTTP 401 Unauthorized"),
            embedder=_embedder,
        )
    assert conn.status == "error_terminal"
    assert conn.last_error_code == "auth_expired"
    assert conn.next_sync_at is None  # excluded from the beat until reconnect


# ── exhausted retries escalate to terminal ──────────────────────────────────
async def test_escalates_to_terminal_after_max_failures(db_session):
    user = await _user(db_session)
    conn = await _conn(db_session, user, consecutive_failures=7)
    with pytest.raises(RuntimeError):
        await _run(db_session, conn, _Boom())
    assert conn.consecutive_failures == 8
    assert conn.status == "error_terminal"  # gave up retrying a transient error


# ── kill-switch defers (no failed run, no items) ────────────────────────────
async def test_killswitch_defers_sync(db_session):
    user = await _user(db_session)
    conn = await _conn(db_session, user)
    await transcription_guard.get_redis().set("mi:killswitch", "1")
    try:
        res = await _run(db_session, conn, _Resource())
    finally:
        await transcription_guard.get_redis().delete("mi:killswitch")
    assert res.status == "deferred"
    runs = (
        await db_session.execute(
            select(McpIngestionRun).where(McpIngestionRun.connection_id == conn.id)
        )
    ).scalars().all()
    assert runs == []  # no run row — a halt is operational, not a fault
    items = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    assert items == []
    assert conn.status == "active"  # unchanged


async def test_killswitch_per_user_defers(db_session):
    user = await _user(db_session)
    conn = await _conn(db_session, user)
    await transcription_guard.get_redis().set(f"mi:killswitch:user:{user.id}", "1")
    try:
        res = await _run(db_session, conn, _Resource())
    finally:
        await transcription_guard.get_redis().delete(f"mi:killswitch:user:{user.id}")
    assert res.status == "deferred"


# ── dispatcher includes transient, excludes terminal/paused/disabled ────────
async def test_dispatch_filter(db_session):
    user = await _user(db_session)
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    active = await _conn(db_session, user, status="active", next_sync_at=past)
    transient = await _conn(db_session, user, status="error_transient", next_sync_at=past)
    terminal = await _conn(db_session, user, status="error_terminal", next_sync_at=past)
    paused = await _conn(db_session, user, status="paused", enabled=False, next_sync_at=past)
    not_due = await _conn(db_session, user, status="active",
                          next_sync_at=datetime.now(timezone.utc) + timedelta(hours=1))

    due = (
        await db_session.execute(due_connections_query(datetime.now(timezone.utc)))
    ).scalars().all()
    due_ids = {c.id for c in due}
    assert active.id in due_ids
    assert transient.id in due_ids  # the bug fix: transient auto-retries
    assert terminal.id not in due_ids
    assert paused.id not in due_ids
    assert not_due.id not in due_ids
