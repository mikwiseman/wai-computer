"""Tests for entity endpoints."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import EntityRelation
from tests.conftest import LEGAL_ACCEPTANCE


async def _register(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_and_filter_entities(client: AsyncClient):
    """Entity list should support filtering by type."""
    headers = await _register(client, "entity.filter@example.com")

    person = await client.post(
        "/api/entities",
        headers=headers,
        json={"type": "person", "name": "Alex", "metadata": {"team": "product"}},
    )
    assert person.status_code == 201

    project = await client.post(
        "/api/entities",
        headers=headers,
        json={"type": "project", "name": "Phoenix"},
    )
    assert project.status_code == 201

    list_response = await client.get("/api/entities", headers=headers, params={"type": "person"})
    assert list_response.status_code == 200
    data = list_response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Alex"
    assert data[0]["metadata"] == {"team": "product"}


@pytest.mark.asyncio
async def test_create_entity_rejects_invalid_type(client: AsyncClient):
    """Entity type should be constrained to allowed values."""
    headers = await _register(client, "entity.invalid@example.com")
    response = await client.post(
        "/api/entities",
        headers=headers,
        json={"type": "unknown", "name": "Bad Entity"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_entity_includes_relations(client: AsyncClient, db_session: AsyncSession):
    """Entity detail should include outgoing relations."""
    headers = await _register(client, "entity.relations@example.com")

    source_response = await client.post(
        "/api/entities",
        headers=headers,
        json={"type": "person", "name": "Dana"},
    )
    target_response = await client.post(
        "/api/entities",
        headers=headers,
        json={"type": "project", "name": "Atlas"},
    )
    assert source_response.status_code == 201
    assert target_response.status_code == 201

    source_id = UUID(source_response.json()["id"])
    target_id = UUID(target_response.json()["id"])

    db_session.add(
        EntityRelation(
            source_id=source_id,
            target_id=target_id,
            relation_type="works_on",
            context="Discussed in planning call",
        )
    )
    await db_session.flush()

    detail_response = await client.get(f"/api/entities/{source_id}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert len(detail["relations"]) == 1
    assert detail["relations"][0]["target_name"] == "Atlas"
    assert detail["relations"][0]["relation_type"] == "works_on"


@pytest.mark.asyncio
async def test_entity_isolation_between_users(client: AsyncClient):
    """Entity access should be scoped to owner."""
    owner_headers = await _register(client, "entity.owner@example.com")
    other_headers = await _register(client, "entity.other@example.com")

    create_response = await client.post(
        "/api/entities",
        headers=owner_headers,
        json={"type": "organization", "name": "Wai"},
    )
    entity_id = create_response.json()["id"]

    get_other = await client.get(f"/api/entities/{entity_id}", headers=other_headers)
    assert get_other.status_code == 404

    delete_other = await client.delete(f"/api/entities/{entity_id}", headers=other_headers)
    assert delete_other.status_code == 404


@pytest.mark.asyncio
async def test_list_entities_empty(client: AsyncClient):
    """A new user with no entities should get an empty list."""
    headers = await _register(client, "entity.empty@example.com")
    response = await client.get("/api/entities", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_delete_nonexistent_entity_returns_404(client: AsyncClient):
    """Deleting a non-existent entity should return 404."""
    headers = await _register(client, "entity.delnone@example.com")
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(f"/api/entities/{fake_id}", headers=headers)
    assert response.status_code == 404
    assert "entity not found" in response.json()["detail"].lower()
