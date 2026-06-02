"""DB-backed tests for the knowledge-graph write helpers (Phase 2)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.entity_graph import (
    record_mention,
    seed_entities_from_summary,
    upsert_entity,
)
from app.models.entity import Entity, EntityMention
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"eg-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_upsert_entity_dedups_on_exact_normalised_name(db_session) -> None:
    user = await _make_user(db_session)
    a1 = await upsert_entity(db_session, user.id, type="person", name="  Anna  ")
    a2 = await upsert_entity(db_session, user.id, type="person", name="Anna")
    assert a1 is not None and a2 is not None
    assert a1.id == a2.id
    assert a1.name == "Anna"  # trimmed / NFC-normalised

    # Different case is a DISTINCT entity (exact-only merge; fuzzy -> Review).
    lower = await upsert_entity(db_session, user.id, type="person", name="anna")
    assert lower is not None and lower.id != a1.id

    # Same name, different type is distinct.
    topic = await upsert_entity(db_session, user.id, type="topic", name="Anna")
    assert topic is not None and topic.id != a1.id

    # Empty / whitespace normalises to None -> no entity created.
    assert await upsert_entity(db_session, user.id, type="topic", name="   ") is None


async def test_record_mention_is_idempotent(db_session) -> None:
    user = await _make_user(db_session)
    entity = await upsert_entity(db_session, user.id, type="topic", name="GPU")
    assert entity is not None
    src = uuid4()
    m1 = await record_mention(
        db_session,
        user_id=user.id,
        entity_id=entity.id,
        source_kind="item",
        source_id=src,
        weight=1.0,
    )
    m2 = await record_mention(
        db_session,
        user_id=user.id,
        entity_id=entity.id,
        source_kind="item",
        source_id=src,
        weight=2.0,
        context="seen again",
    )
    assert m1.id == m2.id
    assert m2.weight == 2.0
    assert m2.context == "seen again"

    rows = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.entity_id == entity.id)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_seed_entities_from_summary_creates_people_and_topics(db_session) -> None:
    user = await _make_user(db_session)
    src = uuid4()
    count = await seed_entities_from_summary(
        db_session,
        user.id,
        source_kind="item",
        source_id=src,
        people=["Anna", "Ben", "  "],  # blank is skipped
        topics=["GPU", "Pricing"],
    )
    assert count == 4  # Anna, Ben, GPU, Pricing (blank skipped)

    entities = (
        await db_session.execute(select(Entity).where(Entity.user_id == user.id))
    ).scalars().all()
    assert {e.type for e in entities} == {"person", "topic"}
    assert {e.name for e in entities} == {"Anna", "Ben", "GPU", "Pricing"}

    mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.source_id == src)
        )
    ).scalars().all()
    assert len(mentions) == 4
    assert all(m.source_kind == "item" for m in mentions)
