"""Tests for recording starring/favoriting feature."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import LEGAL_ACCEPTANCE


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Test Recording",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": "note", "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


async def _register_user(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.mark.asyncio
async def test_star_recording(client: AsyncClient, auth_headers: dict):
    """POST /api/recordings/{id}/star should star the recording."""
    recording = await _create_recording(client, auth_headers, title="Star Me")

    response = await client.post(
        f"/api/recordings/{recording['id']}/star",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == recording["id"]
    assert data["starred_at"] is not None


@pytest.mark.asyncio
async def test_unstar_recording(client: AsyncClient, auth_headers: dict):
    """DELETE /api/recordings/{id}/star should unstar the recording."""
    recording = await _create_recording(client, auth_headers, title="Unstar Me")

    # Star first
    await client.post(f"/api/recordings/{recording['id']}/star", headers=auth_headers)

    # Then unstar
    response = await client.delete(
        f"/api/recordings/{recording['id']}/star",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == recording["id"]
    assert data["starred_at"] is None


@pytest.mark.asyncio
async def test_star_nonexistent_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Starring a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(
        f"/api/recordings/{fake_id}/star",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unstar_nonexistent_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Unstarring a nonexistent recording should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(
        f"/api/recordings/{fake_id}/star",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_star_other_user_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Starring another user's recording should return 404."""
    recording = await _create_recording(client, auth_headers, title="Not Yours")
    other_headers = await _register_user(client, f"other-{uuid4().hex[:8]}@example.com")

    response = await client.post(
        f"/api/recordings/{recording['id']}/star",
        headers=other_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_star_trashed_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Starring a trashed recording should be rejected."""
    recording = await _create_recording(client, auth_headers, title="Trash Star")
    delete_response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    response = await client.post(
        f"/api/recordings/{recording['id']}/star",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unstar_trashed_recording_returns_404(client: AsyncClient, auth_headers: dict):
    """Unstarring a trashed recording should be rejected."""
    recording = await _create_recording(client, auth_headers, title="Trash Unstar")
    await client.post(f"/api/recordings/{recording['id']}/star", headers=auth_headers)
    delete_response = await client.delete(
        f"/api/recordings/{recording['id']}",
        headers=auth_headers,
    )
    assert delete_response.status_code == 204

    response = await client.delete(
        f"/api/recordings/{recording['id']}/star",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_star_already_starred_updates_timestamp(client: AsyncClient, auth_headers: dict):
    """Starring an already-starred recording should update the timestamp."""
    recording = await _create_recording(client, auth_headers, title="Double Star")

    first = await client.post(
        f"/api/recordings/{recording['id']}/star", headers=auth_headers
    )
    first_ts = first.json()["starred_at"]

    second = await client.post(
        f"/api/recordings/{recording['id']}/star", headers=auth_headers
    )
    second_ts = second.json()["starred_at"]

    assert second_ts >= first_ts


@pytest.mark.asyncio
async def test_list_recordings_starred_filter(client: AsyncClient, auth_headers: dict):
    """List recordings with starred=true should only return starred recordings."""
    rec1 = await _create_recording(client, auth_headers, title="Starred One")
    await _create_recording(client, auth_headers, title="Not Starred")

    await client.post(f"/api/recordings/{rec1['id']}/star", headers=auth_headers)

    response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"starred": "true"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == rec1["id"]
    assert data[0]["starred_at"] is not None


@pytest.mark.asyncio
async def test_starred_at_field_in_recording_response(client: AsyncClient, auth_headers: dict):
    """Recording response should include starred_at field."""
    recording = await _create_recording(client, auth_headers, title="Check Field")

    # Unstarred recording should have starred_at=null
    response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["starred_at"] is None

    # Star it
    await client.post(f"/api/recordings/{recording['id']}/star", headers=auth_headers)

    # Now starred_at should be set
    response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["starred_at"] is not None


@pytest.mark.asyncio
async def test_star_requires_auth(client: AsyncClient):
    """Unauthenticated star request should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.post(f"/api/recordings/{fake_id}/star")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unstar_requires_auth(client: AsyncClient):
    """Unauthenticated unstar request should return 401."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(f"/api/recordings/{fake_id}/star")
    assert response.status_code == 401
