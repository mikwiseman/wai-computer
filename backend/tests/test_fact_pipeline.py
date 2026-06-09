"""Tests for bi-temporal fact reconciliation + the entity_facts model (P2)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.entity_graph import apply_fact_reconcile
from app.core.fact_pipeline import CurrentFact, ExtractedFact, decide_fact_actions
from app.models.entity import Entity, EntityFact
from app.models.user import User


def _ef(pred: str, obj: str, h: str | None = None, **kw) -> ExtractedFact:
    return ExtractedFact(predicate=pred, object_text=obj, content_hash=h or f"{pred}:{obj}", **kw)


def _cf(fid: str, pred: str, obj: str, h: str | None = None) -> CurrentFact:
    return CurrentFact(id=fid, predicate=pred, object_text=obj, content_hash=h or f"{pred}:{obj}")


def test_noop_on_exact_and_pred_obj_match() -> None:
    cur = [_cf("c1", "works_at", "Acme")]
    assert decide_fact_actions([_ef("works_at", "Acme")], cur)[0].action == "noop"
    # same predicate+object but a different content_hash -> still a noop
    assert decide_fact_actions([_ef("works_at", "Acme", h="x")], cur)[0].action == "noop"


def test_add_new_predicate_and_multivalued_predicate() -> None:
    new_pred = decide_fact_actions([_ef("lives_in", "Berlin")], [_cf("c1", "works_at", "Acme")])
    assert new_pred[0].action == "add"
    # multi-valued predicate, different object -> values coexist
    multi = decide_fact_actions([_ef("knows", "Bob")], [_cf("c1", "knows", "Alice")])
    assert multi[0].action == "add"


def test_supersede_single_valued_change() -> None:
    d = decide_fact_actions([_ef("works_at", "Globex")], [_cf("c1", "works_at", "Acme")])
    assert d[0].action == "supersede" and d[0].supersedes_id == "c1"


def test_supersede_explicit_hint() -> None:
    cur = [_cf("c1", "knows", "Alice"), _cf("c2", "knows", "Bob")]
    d = decide_fact_actions([_ef("knows", "Alice Smith", supersedes_object="Alice")], cur)
    assert d[0].action == "supersede" and d[0].supersedes_id == "c1"


def test_conflict_single_valued_with_multiple_current() -> None:
    cur = [_cf("c1", "works_at", "Acme"), _cf("c2", "works_at", "Globex")]
    d = decide_fact_actions([_ef("works_at", "Initech")], cur)
    assert d[0].action == "conflict" and d[0].supersedes_id in {"c1", "c2"}


@pytest.mark.asyncio
async def test_entity_fact_persists_current_by_default(db_session) -> None:
    user = User(email=f"ef-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    entity = Entity(user_id=user.id, type="person", name="Pavel")
    db_session.add(entity)
    await db_session.flush()
    fact = EntityFact(
        user_id=user.id, subject_entity_id=entity.id,
        predicate="works_at", object_text="Acme", content_hash="h1",
    )
    db_session.add(fact)
    await db_session.flush()
    assert fact.id is not None
    assert fact.invalid_at is None  # CURRENT iff invalid_at IS NULL


async def _user_and_entity(db):
    user = User(email=f"af-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    entity = Entity(user_id=user.id, type="person", name="Pavel")
    db.add(entity)
    await db.flush()
    return user, entity


def _xf(pred: str, obj: str, **kw) -> ExtractedFact:
    return ExtractedFact(predicate=pred, object_text=obj, content_hash=f"{pred}|{obj}", **kw)


async def _current(db, user_id, subject_id) -> list[EntityFact]:
    return list(
        (
            await db.execute(
                select(EntityFact).where(
                    EntityFact.user_id == user_id,
                    EntityFact.subject_entity_id == subject_id,
                    EntityFact.invalid_at.is_(None),
                )
            )
        ).scalars().all()
    )


@pytest.mark.asyncio
async def test_apply_add_then_supersede_preserves_history(db_session) -> None:
    user, entity = await _user_and_entity(db_session)
    r1 = await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("works_at", "Acme")])
    assert r1.added == 1

    r2 = await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("works_at", "Globex")])
    assert r2.added == 1 and r2.superseded == 1

    cur = await _current(db_session, user.id, entity.id)
    assert {c.object_text for c in cur} == {"Globex"}  # only the current value
    allrows = (
        await db_session.execute(
            select(EntityFact).where(EntityFact.subject_entity_id == entity.id)
        )
    ).scalars().all()
    assert len(allrows) == 2  # nothing deleted
    acme = next(r for r in allrows if r.object_text == "Acme")
    assert acme.invalid_at is not None and acme.superseded_by_id is not None


@pytest.mark.asyncio
async def test_apply_can_reassert_a_superseded_fact(db_session) -> None:
    user, entity = await _user_and_entity(db_session)
    await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("works_at", "Acme")])
    await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("works_at", "Globex")])
    # Re-asserting Acme is allowed (partial unique only blocks a CURRENT duplicate).
    r = await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("works_at", "Acme")])
    assert r.added == 1 and r.superseded == 1
    assert {c.object_text for c in await _current(db_session, user.id, entity.id)} == {"Acme"}


@pytest.mark.asyncio
async def test_apply_noop_on_existing_current_fact(db_session) -> None:
    user, entity = await _user_and_entity(db_session)
    await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("knows", "Alice")])
    r = await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("knows", "Alice")])
    assert r.noop == 1 and r.added == 0


@pytest.mark.asyncio
async def test_apply_conflict_when_multiple_current_single_valued(db_session) -> None:
    user, entity = await _user_and_entity(db_session)
    # Seed an inconsistent state: two CURRENT single-valued facts (allowed — the
    # partial unique index is per-object, not per-predicate).
    for obj, h in [("Acme", "a"), ("Globex", "b")]:
        db_session.add(
            EntityFact(
                user_id=user.id, subject_entity_id=entity.id,
                predicate="works_at", object_text=obj, content_hash=h,
            )
        )
    await db_session.flush()
    r = await apply_fact_reconcile(db_session, user.id, entity.id, [_xf("works_at", "Initech")])
    assert r.added == 1 and r.superseded == 0 and len(r.conflicts) == 1
