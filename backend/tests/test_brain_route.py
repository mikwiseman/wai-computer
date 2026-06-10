"""Tests for the compiled-wiki Brain projection + route."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.core.brain_maps as brain_maps
from app.api.routes.brain import _raise_map_http
from app.core import user_memory as user_memory_module
from app.core.brain import compile_brain
from app.core.brain_maps import (
    BrainMapError,
    BrainMapNotFoundError,
    BrainMapValidationError,
)
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


# --- Brain Maps + Live Mirror routes -----------------------------------------


async def _fake_search(*_args, **_kwargs):
    return []


async def test_brain_mirror_route_returns_projection(client, auth_headers) -> None:
    resp = await client.get("/api/brain/mirror", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["map_type"] == "live_mirror"
    assert isinstance(data["nodes"], list)
    assert "freshness" in data and "citations" in data


async def test_brain_map_routes_full_lifecycle(client, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(brain_maps, "unified_search", _fake_search)

    created = await client.post(
        "/api/brain/maps",
        json={"prompt": "Map my active projects", "origin": "brain"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    data = created.json()
    map_id = data["id"]
    assert data["status"] == "draft"
    assert data["origin"] == "brain"
    assert data["current_revision_id"] == data["current_revision"]["id"]
    assert data["current_revision"]["revision_index"] == 1
    assert data["current_revision"]["projection"]["title"] == "Map my active projects"

    listing = await client.get("/api/brain/maps", headers=auth_headers)
    assert listing.status_code == 200
    assert [m["id"] for m in listing.json()["maps"]] == [map_id]

    fetched = await client.get(f"/api/brain/maps/{map_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == map_id

    updated = await client.patch(
        f"/api/brain/maps/{map_id}",
        json={"title": "Projects", "status": "saved", "layout": {"n1": {"x": 1, "y": 2}}},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Projects"
    assert updated.json()["status"] == "saved"
    assert updated.json()["layout"] == {"n1": {"x": 1, "y": 2}}

    # Sources unchanged -> refresh reuses the current revision instead of
    # minting an identical one (new-revision diffs are covered at core level).
    refreshed = await client.post(f"/api/brain/maps/{map_id}/refresh", headers=auth_headers)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["map_id"] == map_id
    assert refreshed.json()["id"] == data["current_revision"]["id"]

    revisions = await client.get(f"/api/brain/maps/{map_id}/revisions", headers=auth_headers)
    assert revisions.status_code == 200
    assert [r["revision_index"] for r in revisions.json()["revisions"]] == [1]


async def test_brain_map_routes_translate_domain_errors(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(brain_maps, "unified_search", _fake_search)

    missing = await client.get(f"/api/brain/maps/{uuid4()}", headers=auth_headers)
    assert missing.status_code == 404

    invalid = await client.post("/api/brain/maps", json={"prompt": "   "}, headers=auth_headers)
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "prompt is required"

    created = await client.post(
        "/api/brain/maps", json={"prompt": "Map decisions"}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    bad_status = await client.patch(
        f"/api/brain/maps/{created.json()['id']}",
        json={"status": "bogus"},
        headers=auth_headers,
    )
    assert bad_status.status_code == 422

    missing_refresh = await client.post(
        f"/api/brain/maps/{uuid4()}/refresh", headers=auth_headers
    )
    assert missing_refresh.status_code == 404

    missing_revisions = await client.get(
        f"/api/brain/maps/{uuid4()}/revisions", headers=auth_headers
    )
    assert missing_revisions.status_code == 404


async def test_raise_map_http_maps_each_domain_error() -> None:
    with pytest.raises(HTTPException) as not_found:
        _raise_map_http(BrainMapNotFoundError("missing"))
    assert not_found.value.status_code == 404

    with pytest.raises(HTTPException) as invalid:
        _raise_map_http(BrainMapValidationError("bad"))
    assert invalid.value.status_code == 422

    with pytest.raises(HTTPException) as bad_request:
        _raise_map_http(BrainMapError("broken"))
    assert bad_request.value.status_code == 400

    # Anything that is not a Brain Map domain error is re-raised untranslated.
    with pytest.raises(RuntimeError):
        _raise_map_http(RuntimeError("untranslated"))
