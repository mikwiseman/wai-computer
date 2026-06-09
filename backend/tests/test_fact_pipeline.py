"""Tests for bi-temporal fact reconciliation + the entity_facts model (P2)."""

from uuid import uuid4

import pytest

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
