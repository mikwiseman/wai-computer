"""Third coverage pass: comparison routes GET/DELETE + mcp_sync dispatch/lock paths."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


async def _make_two_items(client, auth_headers) -> list[str]:
    ids = []
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        for i in range(2):
            r = await client.post(
                "/api/items",
                json={"source": "paste", "kind": "note", "body": f"b{i} content"},
                headers=auth_headers,
            )
            ids.append(r.json()["id"])
    return ids


@pytest.mark.asyncio
async def test_comparison_get_and_delete_roundtrip(client, auth_headers) -> None:
    ids = await _make_two_items(client, auth_headers)
    with patch("app.tasks.comparison_generation.generate_comparison_task.delay"):
        created = await client.post(
            "/api/comparisons", json={"item_ids": ids}, headers=auth_headers
        )
    cid = created.json()["id"]

    # GET happy path.
    got = await client.get(f"/api/comparisons/{cid}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == cid

    # DELETE happy path, then 404 on re-get + re-delete.
    deleted = await client.delete(f"/api/comparisons/{cid}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/comparisons/{cid}", headers=auth_headers)).status_code == 404
    assert (
        await client.delete(f"/api/comparisons/{cid}", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_comparison_get_missing_404(client, auth_headers) -> None:
    resp = await client.get(f"/api/comparisons/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_due_real_run_with_no_connections(db_session, monkeypatch) -> None:

    from app.tasks import mcp_sync

    @asynccontextmanager
    async def ctx():
        yield db_session

    monkeypatch.setattr(mcp_sync, "get_db_context", ctx)
    # No due connections for a fresh schema -> returns 0, exercises the real loop.
    count = await mcp_sync._dispatch_due()
    assert count == 0


@pytest.mark.asyncio
async def test_dispatch_due_enqueues_and_tolerates_broker_failure(db_session, monkeypatch) -> None:

    from app.models.mcp_connection import McpConnection
    from app.models.user import User
    from app.tasks import mcp_sync

    user = User(email=f"disp2-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conn = McpConnection(
        user_id=user.id, server_label="due", server_url="https://due/mcp",
        enabled=True, next_sync_at=None,
    )
    db_session.add(conn)
    await db_session.flush()

    @asynccontextmanager
    async def ctx():
        yield db_session

    monkeypatch.setattr(mcp_sync, "get_db_context", ctx)
    # Broker .delay raises -> the except branch is exercised, count still counts it.
    with patch.object(mcp_sync.sync_mcp_connection, "delay", side_effect=RuntimeError("no broker")):
        count = await mcp_sync._dispatch_due()
    assert count == 1


def test_redis_client_returns_client_or_none() -> None:
    from app.tasks import mcp_sync

    # With a fake redis module present, _redis_client returns its client.

    sentinel = object()
    fake_redis = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda url: sentinel))
    with patch.dict("sys.modules", {"redis": fake_redis}):
        assert mcp_sync._redis_client() is sentinel


def test_redis_client_swallows_errors() -> None:

    from app.tasks import mcp_sync

    def _boom(url):
        raise RuntimeError("no redis")

    fake_redis = SimpleNamespace(Redis=SimpleNamespace(from_url=_boom))
    with patch.dict("sys.modules", {"redis": fake_redis}):
        assert mcp_sync._redis_client() is None


@pytest.mark.asyncio
async def test_mcp_client_call_tool_via_session() -> None:

    from app.core import mcp_client as mc

    session = SimpleNamespace(
        call_tool=AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(text="result")]))
    )

    @asynccontextmanager
    async def fake_open(url, token):
        yield session

    with patch.object(mc, "_open_session", fake_open):
        out = await mc.McpClient("https://x/mcp", "tok").call_tool("search", {"q": "y"})
    assert out == "result"
    session.call_tool.assert_awaited_once()
