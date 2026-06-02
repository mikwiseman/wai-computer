"""DB-backed tests for the universal item ingestion service (Phase 1)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.item_ingest import ingest_item
from app.models.item import Item, ItemChunk
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"item-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _fake_embedder(texts: list[str]) -> list[list[float]]:
    # Deterministic 1536-d vectors; value encodes the index so we can assert ordering.
    return [[float(i % 7) / 7.0] * 1536 for i, _ in enumerate(texts)]


async def test_ingest_creates_item_and_chunks(db_session) -> None:
    user = await _make_user(db_session)
    body = "\n\n".join(f"Para {i} " + ("token " * 40) for i in range(6))
    item, created = await ingest_item(
        db_session,
        user.id,
        source="paste",
        kind="note",
        title="My Note",
        body=body,
        embedder=_fake_embedder,
    )
    assert created is True
    assert item.state == "raw"
    assert item.content_hash and len(item.content_hash) == 64
    assert item.simhash is not None
    assert item.embedding is not None

    chunks = (
        (await db_session.execute(select(ItemChunk).where(ItemChunk.item_id == item.id)))
        .scalars()
        .all()
    )
    assert len(chunks) >= 1
    # Every chunk carries the contextual header and an embedding.
    for c in chunks:
        assert c.content.startswith("My Note › ")
        assert c.embedding is not None


async def test_ingest_is_idempotent_by_content(db_session) -> None:
    user = await _make_user(db_session)
    first, created1 = await ingest_item(
        db_session, user.id, source="paste", title="T", body="same body text",
        embedder=_fake_embedder,
    )
    second, created2 = await ingest_item(
        db_session, user.id, source="paste", title="T", body="same body text",
        embedder=_fake_embedder,
    )
    assert created1 is True
    assert created2 is False
    assert first.id == second.id
    count = len(
        (await db_session.execute(select(Item).where(Item.user_id == user.id)))
        .scalars()
        .all()
    )
    assert count == 1


async def test_ingest_idempotent_by_url_before_body(db_session) -> None:
    user = await _make_user(db_session)
    url = "https://example.com/watch?v=abc123"
    first, c1 = await ingest_item(
        db_session, user.id, source="url", kind="video", url=url,
        dedup_key=url, body=None, embedder=_fake_embedder,
    )
    # Same URL re-forwarded later (now with a fetched body) must not duplicate.
    second, c2 = await ingest_item(
        db_session, user.id, source="url", kind="video", url=url,
        dedup_key=url, body="fetched transcript body", embedder=_fake_embedder,
    )
    assert c1 is True and c2 is False
    assert first.id == second.id


async def test_ingest_distinct_users_not_deduped(db_session) -> None:
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)
    a, ca = await ingest_item(
        db_session, u1.id, source="paste", body="shared text", embedder=_fake_embedder
    )
    b, cb = await ingest_item(
        db_session, u2.id, source="paste", body="shared text", embedder=_fake_embedder
    )
    assert ca and cb
    assert a.id != b.id


async def test_ingest_without_embedding(db_session) -> None:
    user = await _make_user(db_session)
    item, created = await ingest_item(
        db_session, user.id, source="paste", title="No embed", body="hello world",
        embed=False,
    )
    assert created is True
    assert item.embedding is None
    chunks = (
        (await db_session.execute(select(ItemChunk).where(ItemChunk.item_id == item.id)))
        .scalars()
        .all()
    )
    assert len(chunks) == 1
    assert chunks[0].embedding is None


async def test_ingest_item_race_returns_existing_on_integrity_error(db_session) -> None:
    """Concurrent duplicate: the dedup SELECT misses but the INSERT collides on
    (user_id, content_hash). ingest must return the existing row, never a 500."""
    user = await _make_user(db_session)
    item1, created1 = await ingest_item(
        db_session, user.id, source="paste", body="same body here", embed=False,
    )
    assert created1 is True

    real_execute = db_session.execute
    calls = {"n": 0}

    class _Empty:
        def scalar_one_or_none(self):
            return None

    async def fake_execute(stmt, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Empty()  # hide the existing row from the dedup SELECT
        return await real_execute(stmt, *args, **kwargs)

    db_session.execute = fake_execute  # type: ignore[assignment]
    try:
        item2, created2 = await ingest_item(
            db_session, user.id, source="paste", body="same body here", embed=False,
        )
    finally:
        db_session.execute = real_execute  # type: ignore[assignment]

    assert created2 is False
    assert item2.id == item1.id
