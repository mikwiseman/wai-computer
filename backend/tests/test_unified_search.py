"""DB-backed tests for unified RRF search over recordings + items."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.item_ingest import ingest_item
from app.models.recording import Recording, Segment
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


async def _make_user(db) -> User:
    user = User(email=f"usearch-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _make_recording_with_segment(db, user, *, title, content) -> Recording:
    rec = Recording(user_id=user.id, title=title, type="meeting", status="ready")
    db.add(rec)
    await db.flush()
    db.add(
        Segment(
            recording_id=rec.id,
            content=content,
            start_ms=0,
            end_ms=1000,
            embedding=[0.02] * 1536,
        )
    )
    await db.flush()
    return rec


async def test_unified_search_returns_both_sources(db_session) -> None:
    from app.core.unified_search import unified_search

    user = await _make_user(db_session)
    await _make_recording_with_segment(
        db_session, user, title="Budget Meeting", content="we approved the quarterly budget"
    )
    await ingest_item(
        db_session, user.id, source="paste", kind="article", title="Budget Article",
        body="an article discussing the quarterly budget in detail", embedder=_embedder,
    )

    with patch(
        "app.core.unified_search.generate_embedding", return_value=[0.02] * 1536
    ):
        hits = await unified_search(db_session, user.id, "quarterly budget", limit=10)

    kinds = {h.source_kind for h in hits}
    assert "recording" in kinds
    assert "item" in kinds
    # Every hit carries a usable parent id + snippet + score.
    for h in hits:
        assert h.parent_id
        assert h.snippet
        assert h.score > 0


async def test_unified_search_scopes_to_user(db_session) -> None:
    from app.core.unified_search import unified_search

    user_a = await _make_user(db_session)
    user_b = await _make_user(db_session)
    await ingest_item(
        db_session, user_a.id, source="paste", body="secret alpha content about widgets",
        embedder=_embedder,
    )

    with patch("app.core.unified_search.generate_embedding", return_value=[0.02] * 1536):
        hits_b = await unified_search(db_session, user_b.id, "widgets", limit=10)
    assert hits_b == []


async def test_unified_search_empty_query_returns_empty(db_session) -> None:
    from app.core.unified_search import unified_search

    user = await _make_user(db_session)
    hits = await unified_search(db_session, user.id, "   ", limit=10)
    assert hits == []


async def test_unified_search_route(client, auth_headers, db_session) -> None:
    # Seed an item via the API, then hit /search/all.
    with patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"):
        await client.post(
            "/api/items",
            json={"source": "paste", "kind": "note", "title": "Note",
                  "body": "a note about migratory birds and seasons"},
            headers=auth_headers,
        )
    with patch("app.core.unified_search.generate_embedding", return_value=[0.01] * 1536):
        resp = await client.get("/api/search/all?q=migratory birds", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    assert any(r["source_kind"] == "item" for r in data["results"])
