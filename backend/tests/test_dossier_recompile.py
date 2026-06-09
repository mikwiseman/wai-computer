"""Tests for the living-wiki dossier recompile sweep (P3)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.entity_graph import record_mention, record_relation, upsert_entity
from app.models.user import User
from app.tasks.recompile_entity_dossiers import _recompile_with_db

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    user = User(email=f"d-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


def _enable_recompile(monkeypatch) -> None:
    from app.core import entity_graph as eg

    monkeypatch.setattr(
        eg, "get_settings", lambda: type("S", (), {"brain_dossier_recompile_enabled": True})()
    )


async def test_record_mention_marks_entity_dossier_dirty(db_session, monkeypatch) -> None:
    _enable_recompile(monkeypatch)
    user = await _user(db_session)
    entity = await upsert_entity(db_session, user.id, type="person", name="Pavel")
    await record_mention(
        db_session, user_id=user.id, entity_id=entity.id, source_kind="item", source_id=uuid4()
    )
    await db_session.refresh(entity)
    assert entity.dossier_dirty is True


async def test_record_relation_marks_both_entities_dirty(db_session, monkeypatch) -> None:
    _enable_recompile(monkeypatch)
    user = await _user(db_session)
    alice = await upsert_entity(db_session, user.id, type="person", name="Alice")
    apollo = await upsert_entity(db_session, user.id, type="project", name="Apollo")
    await record_relation(
        db_session, source_entity_id=alice.id, target_entity_id=apollo.id, relation_type="works_on"
    )
    await db_session.refresh(alice)
    await db_session.refresh(apollo)
    assert alice.dossier_dirty and apollo.dossier_dirty


async def test_recompile_clears_dirty_for_sourceless_entity(db_session) -> None:
    user = await _user(db_session)
    entity = await upsert_entity(db_session, user.id, type="person", name="Nobody")
    entity.dossier_dirty = True
    entity.dossier_dirty_at = datetime.now(timezone.utc)
    await db_session.flush()

    result = await _recompile_with_db(db_session, 25)
    assert result["processed"] >= 1
    await db_session.refresh(entity)
    assert entity.dossier_dirty is False  # cleared; sourceless -> skeleton, no LLM
