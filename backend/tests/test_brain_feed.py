"""Tests for the Cards-That-Think home feed (P0b)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.brain_feed import count_new_since_last_seen, get_brain_feed
from app.core.item_ingest import ingest_item
from app.models.recording import Recording, Summary
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


async def _make_user(db) -> User:
    user = User(email=f"feed-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_feed_returns_cards_across_kinds_with_stored_summary(db_session) -> None:
    user = await _make_user(db_session)
    rec = Recording(user_id=user.id, title="Budget meeting", type="meeting", status="ready")
    db_session.add(rec)
    await db_session.flush()
    db_session.add(Summary(recording_id=rec.id, summary="We approved the quarterly budget."))
    await ingest_item(
        db_session, user.id, source="paste", kind="note", title="A note",
        body="some body text", embedder=_embedder,
    )
    await db_session.flush()

    feed = await get_brain_feed(db_session, user.id, limit=10)
    kinds = {c.source_kind for c in feed.cards}
    assert "recording" in kinds and "item" in kinds
    rec_card = next(c for c in feed.cards if c.source_kind == "recording")
    assert "quarterly budget" in rec_card.summary.lower()  # zero-LLM, from stored summary
    assert all(c.id == f"{c.source_kind}:{c.source_id}" for c in feed.cards)


async def test_feed_is_new_flag_and_count(db_session) -> None:
    user = await _make_user(db_session)
    await ingest_item(
        db_session, user.id, source="paste", kind="note", title="New thing",
        body="x", embedder=_embedder,
    )
    await db_session.flush()
    past = datetime.now(timezone.utc) - timedelta(days=1)

    feed = await get_brain_feed(db_session, user.id, limit=10, last_seen=past)
    assert any(c.is_new for c in feed.cards)
    assert await count_new_since_last_seen(db_session, user.id, last_seen=past) >= 1

    feed2 = await get_brain_feed(db_session, user.id, limit=10, last_seen=None)
    assert all(not c.is_new for c in feed2.cards)
    assert await count_new_since_last_seen(db_session, user.id, last_seen=None) == 0


async def test_feed_keyset_pagination_handles_same_timestamp(db_session) -> None:
    # All items share one transaction timestamp; the (time,id) cursor must still
    # paginate without skips or overlap.
    user = await _make_user(db_session)
    for i in range(5):
        await ingest_item(
            db_session, user.id, source="paste", kind="note", title=f"Note {i}",
            body=f"body {i}", embedder=_embedder,
        )
    await db_session.flush()

    page1 = await get_brain_feed(db_session, user.id, limit=2)
    assert len(page1.cards) == 2 and page1.next_cursor
    page2 = await get_brain_feed(db_session, user.id, limit=2, cursor=page1.next_cursor)
    assert len(page2.cards) == 2 and page2.next_cursor
    page3 = await get_brain_feed(db_session, user.id, limit=2, cursor=page2.next_cursor)
    assert len(page3.cards) == 1 and page3.next_cursor is None  # 5 items over 3 pages
    ids = [c.id for p in (page1, page2, page3) for c in p.cards]
    assert len(ids) == len(set(ids)) == 5  # no overlap, no skips


async def test_feed_routes(client, auth_headers) -> None:
    with (
        patch("app.core.item_ingest.generate_embeddings", _embedder),
        patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"),
    ):
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "title": "Routed note", "body": "hello"},
            headers=auth_headers,
        )
    resp = await client.get("/api/brain/feed?limit=5", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert any(c["source_kind"] == "item" for c in resp.json()["cards"])

    assert (await client.get("/api/brain/since-last-seen", headers=auth_headers)).status_code == 200
    seen = await client.post("/api/brain/seen", headers=auth_headers)
    assert seen.status_code == 200 and seen.json()["seen_at"]
