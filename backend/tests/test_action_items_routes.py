"""Tests for action-item routes."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import ActionItem, Recording
from app.models.user import User


async def _register(client: AsyncClient, email: str, password: str = "password123") -> dict:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed_action_item(
    db_session: AsyncSession,
    email: str,
    task: str,
    *,
    status: str = "pending",
    priority: str = "medium",
) -> ActionItem:
    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(email=email, password_hash="hash")
        db_session.add(user)
        await db_session.flush()

    recording = Recording(user_id=user.id, title="Seed", type="note", language="en")
    db_session.add(recording)
    await db_session.flush()

    item = ActionItem(
        recording_id=recording.id,
        task=task,
        status=status,
        priority=priority,
        due_date=date(2026, 3, 5),
    )
    db_session.add(item)
    await db_session.flush()
    return item


@pytest.mark.asyncio
async def test_list_action_items_filters(client: AsyncClient, db_session: AsyncSession):
    """Listing should honor status and priority filters."""
    headers = await _register(client, "action.filter@example.com")

    first = await _seed_action_item(
        db_session,
        "action.filter@example.com",
        "High pending",
        status="pending",
        priority="high",
    )
    await _seed_action_item(
        db_session,
        "action.filter@example.com",
        "Completed low",
        status="completed",
        priority="low",
    )

    response = await client.get(
        "/api/action-items",
        headers=headers,
        params={"status": "pending", "priority": "high"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == str(first.id)


@pytest.mark.asyncio
async def test_update_action_item_invalid_due_date_returns_400(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Invalid due-date format should return a validation error."""
    headers = await _register(client, "action.update@example.com")
    item = await _seed_action_item(db_session, "action.update@example.com", "Task to update")

    response = await client.patch(
        f"/api/action-items/{item.id}",
        headers=headers,
        json={"due_date": "invalid-date"},
    )
    assert response.status_code == 400
    assert "yyyy-mm-dd" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_action_item_rejects_invalid_status_enum(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Status should be constrained to known enum values."""
    headers = await _register(client, "action.status@example.com")
    item = await _seed_action_item(db_session, "action.status@example.com", "Task with status")

    response = await client.patch(
        f"/api/action-items/{item.id}",
        headers=headers,
        json={"status": "done"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_action_item_isolation_between_users(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Users should not access or mutate action items they don't own."""
    owner_headers = await _register(client, "owner@example.com")
    other_headers = await _register(client, "other@example.com")
    item = await _seed_action_item(db_session, "owner@example.com", "Owner task")

    get_response = await client.get(f"/api/action-items/{item.id}", headers=other_headers)
    assert get_response.status_code == 404

    delete_response = await client.delete(f"/api/action-items/{item.id}", headers=other_headers)
    assert delete_response.status_code == 404

    owner_delete = await client.delete(f"/api/action-items/{item.id}", headers=owner_headers)
    assert owner_delete.status_code == 204


@pytest.mark.asyncio
async def test_list_action_items_rejects_invalid_query_enum(client: AsyncClient):
    """Invalid filter enums should fail validation."""
    headers = await _register(client, "action.enum@example.com")
    response = await client.get("/api/action-items", headers=headers, params={"priority": "urgent"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_action_item_allows_clearing_nullable_fields(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Sending null for nullable fields should clear them."""
    headers = await _register(client, "action.clear@example.com")
    item = await _seed_action_item(db_session, "action.clear@example.com", "Task to clear")

    response = await client.patch(
        f"/api/action-items/{item.id}",
        headers=headers,
        json={"owner": None, "due_date": None},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["owner"] is None
    assert payload["due_date"] is None


@pytest.mark.asyncio
async def test_update_action_item_nonexistent_returns_404(
    client: AsyncClient,
):
    """Updating a nonexistent action item should return 404."""
    headers = await _register(client, "action.noitem@example.com")
    fake_uuid = "00000000-0000-0000-0000-000000000000"

    response = await client.patch(
        f"/api/action-items/{fake_uuid}",
        headers=headers,
        json={"status": "completed"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_action_item_other_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Updating another user's action item should return 404."""
    await _register(client, "action.owner2@example.com")
    intruder_headers = await _register(client, "action.intruder@example.com")
    item = await _seed_action_item(db_session, "action.owner2@example.com", "Private task")

    response = await client.patch(
        f"/api/action-items/{item.id}",
        headers=intruder_headers,
        json={"status": "completed"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
