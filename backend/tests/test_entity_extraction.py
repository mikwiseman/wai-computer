"""Recording -> typed entities + relations wiring (Brain-wiki P0).

Covers the new extraction path that makes entity wiki pages rich:
``record_relation`` (the edge every path silently dropped), the typed
``seed_entities_from_extraction``, and the ``apply_summary_result`` hook with
its summary-seed floor on extractor failure.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.entity_graph import (
    backfill_entity_extraction_for_recordings,
    record_relation,
    seed_entities_from_extraction,
    upsert_entity,
)
from app.core.summarizer import EntityResult, SummaryResult
from app.core.summary_generation import apply_summary_result
from app.models.entity import Entity, EntityMention, EntityRelation
from app.models.recording import Recording, RecordingStatus, Segment, Summary
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"ext-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _recording_with_segments(db, user: User) -> Recording:
    recording = Recording(
        user_id=user.id,
        title=None,
        type="meeting",
        status=RecordingStatus.READY.value,
        language="multi",
    )
    db.add(recording)
    await db.flush()
    db.add_all(
        [
            Segment(
                recording_id=recording.id,
                speaker="Speaker 1",
                content="Anna leads the Atlas launch.",
                start_ms=0,
                end_ms=4000,
                confidence=0.95,
            ),
            Segment(
                recording_id=recording.id,
                speaker="Speaker 2",
                content="Acme is the vendor for Atlas.",
                start_ms=4000,
                end_ms=8000,
                confidence=0.9,
            ),
        ]
    )
    await db.flush()
    # Re-fetch with the same eager loads production's loader uses
    # (apply_summary_result reads these relationships synchronously).
    return (
        await db.execute(
            select(Recording)
            .options(
                selectinload(Recording.segments),
                selectinload(Recording.summary),
                selectinload(Recording.action_items),
                selectinload(Recording.highlights),
            )
            .where(Recording.id == recording.id)
        )
    ).scalar_one()


def _summary_result() -> SummaryResult:
    return SummaryResult(
        title="Atlas sync",
        summary="Anna leads Atlas; Acme is the vendor.",
        key_points=[],
        decisions=[],
        action_items=[],
        topics=["Atlas"],
        people_mentioned=["Anna"],
        follow_up_questions=[],
        sentiment="neutral",
        highlights=[],
    )


async def test_record_relation_is_idempotent_and_skips_self_loops(db_session) -> None:
    user = await _make_user(db_session)
    anna = await upsert_entity(db_session, user.id, type="person", name="Anna")
    atlas = await upsert_entity(db_session, user.id, type="project", name="Atlas")

    r1 = await record_relation(
        db_session, source_entity_id=anna.id, target_entity_id=atlas.id, relation_type="works_on"
    )
    r2 = await record_relation(
        db_session, source_entity_id=anna.id, target_entity_id=atlas.id, relation_type="works_on"
    )
    assert r1 is not None and r2 is not None and r1.id == r2.id

    rels = (await db_session.execute(select(EntityRelation))).scalars().all()
    assert len(rels) == 1

    # self-loops are never recorded
    assert (
        await record_relation(
            db_session, source_entity_id=anna.id, target_entity_id=anna.id, relation_type="x"
        )
        is None
    )


async def test_seed_extraction_keeps_types_and_writes_relations(db_session) -> None:
    user = await _make_user(db_session)
    source_id = uuid4()
    entities = [
        EntityResult(
            name="Anna",
            type="person",
            context="Lead PM",
            relations=[{"related_to": "Atlas", "relation_type": "works_on"}],
        ),
        EntityResult(name="Atlas", type="project", context="Q3 launch", relations=[]),
        EntityResult(name="Acme", type="organization", context="Vendor", relations=[]),
    ]
    result = await seed_entities_from_extraction(
        db_session,
        user.id,
        source_kind="recording",
        source_id=source_id,
        entities=entities,
        recording_id=None,  # FK-free: relation linkage is covered by the hook test
    )
    assert result.mentions_recorded == 3
    assert result.relations_recorded == 1
    assert result.persons_seeded == 1

    typed = {
        (e.type, e.name)
        for e in (
            await db_session.execute(select(Entity).where(Entity.user_id == user.id))
        ).scalars()
    }
    # organization is kept DISTINCT (not collapsed to a topic node)
    assert ("organization", "Acme") in typed
    assert ("project", "Atlas") in typed
    assert ("person", "Anna") in typed

    rels = (await db_session.execute(select(EntityRelation))).scalars().all()
    assert len(rels) == 1
    assert rels[0].relation_type == "works_on"


async def test_apply_summary_result_extracts_typed_entities_and_relations(db_session) -> None:
    user = await _make_user(db_session)
    recording = await _recording_with_segments(db_session, user)

    async def fake_extractor(_transcript: str) -> list[EntityResult]:
        return [
            EntityResult(
                name="Anna",
                type="person",
                context="Lead",
                relations=[{"related_to": "Atlas", "relation_type": "works_on"}],
            ),
            EntityResult(name="Atlas", type="project", context="launch", relations=[]),
            EntityResult(name="Acme", type="organization", context="vendor", relations=[]),
        ]

    summary = await apply_summary_result(
        db_session,
        recording=recording,
        summary_result=_summary_result(),
        entity_extractor=fake_extractor,
    )
    assert summary is not None

    mentions = (
        await db_session.execute(
            select(EntityMention).where(
                EntityMention.source_kind == "recording",
                EntityMention.source_id == recording.id,
            )
        )
    ).scalars().all()
    assert {m.entity_id for m in mentions}  # at least one mention recorded
    names = {
        (e.type, e.name)
        for e in (
            await db_session.execute(select(Entity).where(Entity.user_id == user.id))
        ).scalars()
    }
    assert ("organization", "Acme") in names

    rels = (await db_session.execute(select(EntityRelation))).scalars().all()
    assert len(rels) == 1
    assert rels[0].relation_type == "works_on"
    # the edge is provenance-linked back to the recording
    assert rels[0].recording_id == recording.id


async def test_apply_summary_result_falls_back_to_summary_seed_on_error(db_session) -> None:
    user = await _make_user(db_session)
    recording = await _recording_with_segments(db_session, user)

    async def boom(_transcript: str) -> list[EntityResult]:
        raise RuntimeError("cerebras down")

    # Extractor blows up — the summary must still persist and the recording must
    # still join the graph via the zero-cost summary seed (people/topics).
    summary = await apply_summary_result(
        db_session,
        recording=recording,
        summary_result=_summary_result(),
        entity_extractor=boom,
    )
    assert summary is not None
    assert recording.summary is not None

    names = {
        e.name
        for e in (
            await db_session.execute(select(Entity).where(Entity.user_id == user.id))
        ).scalars()
    }
    assert "Anna" in names  # from summary_result.people_mentioned
    assert "Atlas" in names  # from summary_result.topics
    # summary seed never writes entity->entity relations
    assert (await db_session.execute(select(EntityRelation))).scalars().first() is None


async def test_backfill_targets_unextracted_recordings_then_skips_them(db_session) -> None:
    user = await _make_user(db_session)
    recording = await _recording_with_segments(db_session, user)
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Anna leads Atlas.",
            sentiment="neutral",
            people_mentioned=["Anna"],
            topics=["Atlas"],
        )
    )
    await db_session.flush()

    calls = {"n": 0}

    async def fake(_transcript: str) -> list[EntityResult]:
        calls["n"] += 1
        return [
            EntityResult(
                name="Anna",
                type="person",
                context="lead",
                relations=[{"related_to": "Atlas", "relation_type": "works_on"}],
            ),
            EntityResult(name="Atlas", type="project", context="launch", relations=[]),
        ]

    first = await backfill_entity_extraction_for_recordings(
        db_session, user.id, limit=10, extractor=fake
    )
    assert first.recordings_scanned == 1
    assert first.recordings_extracted == 1
    assert first.relations_recorded == 1
    assert first.llm_requests == 1
    assert calls["n"] == 1

    # The recording now carries an EntityRelation.recording_id, so a second pass
    # skips it — no repeat Cerebras spend.
    second = await backfill_entity_extraction_for_recordings(
        db_session, user.id, limit=10, extractor=fake
    )
    assert second.recordings_scanned == 0
    assert second.llm_requests == 0
    assert calls["n"] == 1
