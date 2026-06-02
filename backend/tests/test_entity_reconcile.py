"""Person↔Entity reconcile — exact normalised-name auto-link, no silent fuzzy merge."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import entity_graph
from app.core.entity_reconcile import reconcile_person_entities
from app.models.entity import Entity
from app.models.person import Person
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _user(db) -> User:
    u = User(email=f"rec-{uuid4().hex}@example.com", password_hash="x")
    db.add(u)
    await db.flush()
    return u


async def test_links_entity_to_person_by_display_name(db_session) -> None:
    u = await _user(db_session)
    db_session.add(Person(user_id=u.id, display_name="Anna Petrova"))
    db_session.add(Entity(user_id=u.id, type="person", name="Anna Petrova"))
    # A topic with the same string must NOT be linked — only person entities.
    db_session.add(Entity(user_id=u.id, type="topic", name="Anna Petrova"))
    await db_session.flush()

    assert await reconcile_person_entities(db_session, u.id) == 1
    person = (
        await db_session.execute(select(Person).where(Person.user_id == u.id))
    ).scalar_one()
    ent = (
        await db_session.execute(
            select(Entity).where(Entity.user_id == u.id, Entity.type == "person")
        )
    ).scalar_one()
    assert ent.metadata_["person_id"] == str(person.id)


async def test_links_by_alias(db_session) -> None:
    u = await _user(db_session)
    db_session.add(Person(user_id=u.id, display_name="Robert", aliases=["Bob"]))
    db_session.add(Entity(user_id=u.id, type="person", name="Bob"))
    await db_session.flush()
    assert await reconcile_person_entities(db_session, u.id) == 1


async def test_no_match_leaves_unlinked(db_session) -> None:
    u = await _user(db_session)
    db_session.add(Person(user_id=u.id, display_name="Anna"))
    db_session.add(Entity(user_id=u.id, type="person", name="Boris"))
    await db_session.flush()
    assert await reconcile_person_entities(db_session, u.id) == 0
    ent = (
        await db_session.execute(select(Entity).where(Entity.user_id == u.id))
    ).scalar_one()
    assert not (ent.metadata_ or {}).get("person_id")


async def test_idempotent(db_session) -> None:
    u = await _user(db_session)
    db_session.add(Person(user_id=u.id, display_name="Anna"))
    db_session.add(Entity(user_id=u.id, type="person", name="Anna"))
    await db_session.flush()
    assert await reconcile_person_entities(db_session, u.id) == 1
    assert await reconcile_person_entities(db_session, u.id) == 0  # already linked


async def test_no_people_is_noop(db_session) -> None:
    u = await _user(db_session)
    db_session.add(Entity(user_id=u.id, type="person", name="Anna"))
    await db_session.flush()
    assert await reconcile_person_entities(db_session, u.id) == 0


async def test_seed_from_summary_triggers_reconcile(db_session) -> None:
    # The seed hot-path links a freshly-seeded person entity to a known speaker.
    u = await _user(db_session)
    db_session.add(Person(user_id=u.id, display_name="Carol"))
    await db_session.flush()

    await entity_graph.seed_entities_from_summary(
        db_session,
        u.id,
        source_kind="item",
        source_id=uuid4(),
        people=["Carol"],
        topics=[],
    )

    ent = (
        await db_session.execute(
            select(Entity).where(
                Entity.user_id == u.id, Entity.type == "person", Entity.name == "Carol"
            )
        )
    ).scalar_one()
    person = (
        await db_session.execute(select(Person).where(Person.user_id == u.id))
    ).scalar_one()
    assert ent.metadata_["person_id"] == str(person.id)
