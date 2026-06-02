"""Tests for the compiled-wiki Brain projection + route."""

from uuid import uuid4

import pytest

from app.core import user_memory as user_memory_module
from app.core.brain import compile_brain
from app.models.entity import Entity, EntityRelation
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"brain-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_compile_brain_seeds_memory_sections(db_session) -> None:
    user = await _make_user(db_session)
    projection = await compile_brain(db_session, user.id)
    # All BLOCK_SPECS labels present even with no prior memory.
    labels = {s.label for s in projection.memory_sections}
    assert set(user_memory_module.BLOCK_SPECS).issubset(labels)
    assert projection.entity_count == 0
    assert projection.entity_pages == []


async def test_compile_brain_renders_entities_and_relations(db_session) -> None:
    user = await _make_user(db_session)
    alice = Entity(user_id=user.id, type="person", name="Alice")
    project = Entity(user_id=user.id, type="project", name="Apollo")
    db_session.add_all([alice, project])
    await db_session.flush()
    db_session.add(
        EntityRelation(
            source_id=alice.id, target_id=project.id,
            relation_type="works_on", context="leads the Apollo project",
        )
    )
    await db_session.flush()

    projection = await compile_brain(db_session, user.id)
    assert projection.entity_count == 2
    alice_page = next(p for p in projection.entity_pages if p.name == "Alice")
    assert alice_page.type == "person"
    assert len(alice_page.relations) == 1
    rel = alice_page.relations[0]
    assert rel.relation_type == "works_on"
    assert rel.target_name == "Apollo"
    assert rel.target_type == "project"


async def test_compile_brain_reflects_written_memory(db_session) -> None:
    user = await _make_user(db_session)
    await user_memory_module.write_block(
        db_session, user.id, label="human", operation="append",
        content="Lives in Lisbon.", source="system",
    )
    projection = await compile_brain(db_session, user.id)
    human = next(s for s in projection.memory_sections if s.label == "human")
    assert "Lisbon" in human.body


async def test_brain_route_returns_projection(client, auth_headers) -> None:
    resp = await client.get("/api/brain", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "memory_sections" in data
    assert "entity_pages" in data
    assert isinstance(data["entity_count"], int)
    # Seeded memory labels are present.
    labels = {s["label"] for s in data["memory_sections"]}
    assert "human" in labels


async def test_brain_route_scoped_to_user(client, auth_headers, db_session) -> None:
    # Another user's entity must not leak into this user's brain.
    other = await _make_user(db_session)
    db_session.add(Entity(user_id=other.id, type="topic", name="SecretTopic"))
    await db_session.flush()
    resp = await client.get("/api/brain", headers=auth_headers)
    names = {p["name"] for p in resp.json()["entity_pages"]}
    assert "SecretTopic" not in names
