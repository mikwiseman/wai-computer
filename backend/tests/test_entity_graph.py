"""DB-backed tests for the knowledge-graph write helpers (Phase 2)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

import app.core.entity_graph as entity_graph_module
from app.core.entity_graph import (
    _mark_dossier_dirty,
    backfill_entity_mentions_from_existing_summaries,
    record_mention,
    seed_entities_from_summary,
    upsert_entity,
)
from app.models.entity import Entity, EntityMention
from app.models.item import Item, ItemSummary
from app.models.recording import Recording, RecordingStatus, Summary
from app.models.user import User

pytestmark = pytest.mark.asyncio


class _MissResult:
    """A select result that reports 'no row' — used to simulate the lookup
    losing a race against a concurrent insert of the same key."""

    def scalars(self):
        return self

    def first(self):
        return None

    def scalar_one_or_none(self):
        return None


def _miss_first_selects(db_session, monkeypatch, misses: int) -> None:
    """Make the first ``misses`` selects miss, then pass through to the DB."""
    real_execute = db_session.execute
    remaining = {"left": misses}

    async def execute_with_misses(*args, **kwargs):
        if remaining["left"] > 0:
            remaining["left"] -= 1
            return _MissResult()
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", execute_with_misses)


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


async def test_backfill_prioritizes_missing_summary_mentions_under_limit(db_session) -> None:
    user = await _make_user(db_session)
    already_synced = Recording(
        user_id=user.id,
        title="Already synced",
        type="note",
        status=RecordingStatus.READY.value,
    )
    missing = Recording(
        user_id=user.id,
        title="Missing graph links",
        type="note",
        status=RecordingStatus.READY.value,
    )
    db_session.add_all([already_synced, missing])
    await db_session.flush()
    db_session.add_all(
        [
            Summary(
                recording_id=already_synced.id,
                summary="Anna discussed pricing.",
                key_points=[],
                decisions=[],
                topics=["Pricing"],
                people_mentioned=["Anna"],
            ),
            Summary(
                recording_id=missing.id,
                summary="Mik discussed launch.",
                key_points=[],
                decisions=[],
                topics=["Launch"],
                people_mentioned=["Mik"],
            ),
        ]
    )
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    assert anna is not None
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=anna.id,
        source_kind="recording",
        source_id=already_synced.id,
    )

    result = await backfill_entity_mentions_from_existing_summaries(
        db_session,
        user.id,
        limit=1,
    )

    assert result.recording_summaries_scanned == 1
    assert result.item_summaries_scanned == 0
    assert result.sources_with_entities == 1
    assert result.created_mentions == 2
    mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.source_id == missing.id)
        )
    ).scalars().all()
    assert len(mentions) == 2


async def test_upsert_entity_identity_key_collapses_renames(db_session) -> None:
    user = await _make_user(db_session)
    plain = await upsert_entity(db_session, user.id, type="person", name="Greg")
    assert plain is not None and plain.metadata_ is None

    # Same exact name + a new identity key -> the key is attached to the node.
    keyed = await upsert_entity(
        db_session, user.id, type="person", name="Greg", identity_key="Greg@Example.com"
    )
    assert keyed is not None and keyed.id == plain.id
    assert keyed.metadata_["identity_keys"] == ["greg@example.com"]

    # A NEW display name but the same address collapses onto the same node.
    renamed = await upsert_entity(
        db_session, user.id, type="person", name="Greg Smith", identity_key="greg@example.com"
    )
    assert renamed is not None and renamed.id == plain.id

    # An unseen identity key + unseen name creates a keyed node from scratch.
    fresh = await upsert_entity(
        db_session, user.id, type="person", name="Dana", identity_key="dana@example.com"
    )
    assert fresh is not None and fresh.id != plain.id
    assert fresh.metadata_ == {"identity_keys": ["dana@example.com"]}


async def test_upsert_entity_race_returns_winner_and_attaches_identity(
    db_session, monkeypatch
) -> None:
    user = await _make_user(db_session)
    winner = Entity(user_id=user.id, type="person", name="Race")
    db_session.add(winner)
    await db_session.flush()

    # Identity + name lookups both miss, so the insert hits the unique
    # constraint exactly like a concurrent writer would.
    _miss_first_selects(db_session, monkeypatch, misses=2)
    raced = await upsert_entity(
        db_session, user.id, type="person", name="Race", identity_key="race@example.com"
    )

    assert raced is not None and raced.id == winner.id
    assert raced.metadata_["identity_keys"] == ["race@example.com"]


async def test_record_mention_race_returns_winning_row(db_session, monkeypatch) -> None:
    user = await _make_user(db_session)
    entity = await upsert_entity(db_session, user.id, type="topic", name="RaceTopic")
    assert entity is not None
    src = uuid4()
    winner = EntityMention(
        user_id=user.id,
        entity_id=entity.id,
        source_kind="item",
        source_id=src,
        weight=1.0,
    )
    db_session.add(winner)
    await db_session.flush()

    # The dedup select misses, the insert collides, and the winning row returns.
    _miss_first_selects(db_session, monkeypatch, misses=1)
    raced = await record_mention(
        db_session,
        user_id=user.id,
        entity_id=entity.id,
        source_kind="item",
        source_id=src,
    )

    assert raced.id == winner.id


async def test_mark_dossier_dirty_skips_when_no_ids(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        entity_graph_module,
        "get_settings",
        lambda: type("S", (), {"brain_dossier_recompile_enabled": True})(),
    )
    # All-None entity ids -> the helper returns before issuing any UPDATE.
    await _mark_dossier_dirty(db_session, None)
    assert (await db_session.execute(select(Entity))).scalars().first() is None


async def test_backfill_covers_item_summaries_and_reports_counts(db_session) -> None:
    user = await _make_user(db_session)
    item = Item(
        user_id=user.id,
        source="paste",
        kind="note",
        title="Note",
        body="GPU pricing note",
        content_hash=f"backfill-{uuid4().hex}",
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Pricing news.",
            key_points=[],
            action_items=[],
            topics=["Pricing"],
            people_mentioned=["Dana"],
            highlights=[],
            key_moments=[],
            sentiment="neutral",
        )
    )
    await db_session.flush()

    result = await backfill_entity_mentions_from_existing_summaries(db_session, user.id)

    assert result.recording_summaries_scanned == 0
    assert result.item_summaries_scanned == 1
    assert result.sources_with_entities == 1
    assert result.mentions_recorded == 2
    payload = result.as_dict()
    assert payload["item_summaries_scanned"] == 1
    assert payload["created_mentions"] == 2
    assert payload["llm_requests"] == 0

    mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.source_id == item.id)
        )
    ).scalars().all()
    assert {m.source_kind for m in mentions} == {"item"}
    assert len(mentions) == 2
