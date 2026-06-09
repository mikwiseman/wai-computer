"""Forget/restore — reversible archive that hides an item from recall (P4)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.brain_feed import get_brain_feed
from app.core.item_ingest import ingest_item
from app.core.mcp_brain_tools import forget_for_mcp
from app.core.unified_search import unified_search
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.02] * 1536 for _ in texts]


async def _make_user(db) -> User:
    user = User(email=f"forget-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_forget_hides_item_from_search_and_feed_reversibly(db_session) -> None:
    user = await _make_user(db_session)
    item, _ = await ingest_item(
        db_session, user.id, source="paste", kind="note", title="Secret plan",
        body="the migratory falcon project", embedder=_embedder,
    )
    await db_session.flush()

    with patch("app.core.unified_search.generate_embedding", return_value=[0.02] * 1536):
        before = await unified_search(db_session, user.id, "migratory falcon", limit=10)
    assert any(h.parent_id == str(item.id) for h in before)
    feed_before = await get_brain_feed(db_session, user.id, limit=20)
    assert any(c.source_id == str(item.id) for c in feed_before.cards)

    res = await forget_for_mcp(db_session, user.id, str(item.id))
    assert res["forgotten"] is True
    await db_session.flush()

    with patch("app.core.unified_search.generate_embedding", return_value=[0.02] * 1536):
        after = await unified_search(db_session, user.id, "migratory falcon", limit=10)
    assert all(h.parent_id != str(item.id) for h in after)  # gone from recall
    feed_after = await get_brain_feed(db_session, user.id, limit=20)
    assert all(c.source_id != str(item.id) for c in feed_after.cards)  # gone from feed


async def test_forget_for_mcp_rejects_unknown_or_non_uuid(db_session) -> None:
    user = await _make_user(db_session)
    with pytest.raises(ValueError):
        await forget_for_mcp(db_session, user.id, str(uuid4()))  # valid uuid, no such item
    with pytest.raises(ValueError):
        await forget_for_mcp(db_session, user.id, "not-a-uuid")


async def test_forget_restore_routes(client, auth_headers) -> None:
    with (
        patch("app.core.item_ingest.generate_embeddings", _embedder),
        patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"),
    ):
        resp = await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "title": "Routed", "body": "hello forget"},
            headers=auth_headers,
        )
    item_id = resp.json()["id"]

    forgotten = await client.post(f"/api/items/{item_id}/forget", headers=auth_headers)
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json()["state"] == "archived"

    restored = await client.post(f"/api/items/{item_id}/restore", headers=auth_headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["state"] == "raw"
