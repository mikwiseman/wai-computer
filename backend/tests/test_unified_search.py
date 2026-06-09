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
    assert next(h for h in hits if h.source_kind == "recording").start_ms == 0
    assert next(h for h in hits if h.source_kind == "item").start_ms is None
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
    with (
        patch("app.core.item_ingest.generate_embeddings", _embedder),
        patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"),
    ):
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


async def _add_segment(db, rec, *, content, start_ms) -> None:
    db.add(
        Segment(
            recording_id=rec.id,
            content=content,
            start_ms=start_ms,
            end_ms=start_ms + 1000,
            embedding=[0.02] * 1536,
        )
    )
    await db.flush()


async def test_unified_search_max_pool_collapses_per_parent(db_session) -> None:
    """per_parent_limit=1 keeps one chunk per source so a long recording with
    many matching segments can't bury a short note; the legacy default (None)
    keeps every chunk."""
    from app.core.unified_search import unified_search

    user = await _make_user(db_session)
    rec = await _make_recording_with_segment(
        db_session, user, title="Long Budget Meeting", content="the quarterly budget intro"
    )
    await _add_segment(db_session, rec, content="more quarterly budget discussion", start_ms=2000)
    await _add_segment(db_session, rec, content="final quarterly budget decisions", start_ms=4000)
    await ingest_item(
        db_session, user.id, source="paste", kind="note", title="Budget Note",
        body="a short note about the quarterly budget", embedder=_embedder,
    )

    with patch("app.core.unified_search.generate_embedding", return_value=[0.02] * 1536):
        deduped = await unified_search(
            db_session, user.id, "quarterly budget", limit=10, per_parent_limit=1
        )
        legacy = await unified_search(db_session, user.id, "quarterly budget", limit=10)

    # Max-pool: at most one hit per (source_kind, parent_id).
    seen = [(h.source_kind, h.parent_id) for h in deduped]
    assert len(seen) == len(set(seen)), f"duplicate parents leaked: {seen}"
    # The long recording must not crowd out the short note.
    assert any(h.source_kind == "item" for h in deduped)
    assert any(h.source_kind == "recording" and h.parent_id == str(rec.id) for h in deduped)
    # Legacy path (no per_parent_limit) keeps multiple chunks of the same recording.
    rec_chunks_legacy = [
        h for h in legacy if h.source_kind == "recording" and h.parent_id == str(rec.id)
    ]
    assert len(rec_chunks_legacy) >= 2, "legacy path should keep multiple chunks per parent"


async def test_ranking_v2_authority_reorders_when_enabled(db_session, monkeypatch) -> None:
    """With the trust-weighted ranking flag ON, a higher-authority source outranks
    a lower-authority one at equal relevance. (OFF is covered by every other test.)"""
    from app.core import unified_search as us

    user = await _make_user(db_session)
    low, _ = await ingest_item(
        db_session, user.id, source="agent", kind="note", title="Low",
        body="the quarterly budget plan alpha", authority_score=0.3, embedder=_embedder,
    )
    high, _ = await ingest_item(
        db_session, user.id, source="paste", kind="note", title="High",
        body="the quarterly budget plan beta", authority_score=0.9, embedder=_embedder,
    )
    await db_session.flush()

    monkeypatch.setattr(
        us, "get_settings", lambda: type("S", (), {"brain_ranking_v2_enabled": True})()
    )
    with patch("app.core.unified_search.generate_embedding", return_value=[0.02] * 1536):
        hits = await us.unified_search(
            db_session, user.id, "quarterly budget", limit=10, per_parent_limit=1
        )
    order = [h.parent_id for h in hits if h.source_kind == "item"]
    assert order.index(str(high.id)) < order.index(str(low.id))
