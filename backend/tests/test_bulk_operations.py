"""Tests for bulk recording operations endpoint."""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recording import Recording


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Bulk Test",
    type_: str = "note",
) -> dict:
    response = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert response.status_code == 201
    return response.json()


async def _create_folder(client: AsyncClient, headers: dict, name: str) -> dict:
    response = await client.post(
        "/api/folders", headers=headers, json={"name": name}
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_bulk_delete_soft_deletes_multiple_recordings(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Bulk delete should soft-delete all specified recordings."""
    rec1 = await _create_recording(client, auth_headers, title="Bulk Del 1")
    rec2 = await _create_recording(client, auth_headers, title="Bulk Del 2")
    rec3 = await _create_recording(client, auth_headers, title="Untouched")

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec1["id"], rec2["id"]],
            "action": "delete",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 2
    assert payload["failed"] == 0

    # Verify soft-deleted
    for rec_id in [rec1["id"], rec2["id"]]:
        r = await db_session.get(Recording, UUID(rec_id))
        assert r.deleted_at is not None

    # Verify untouched
    r3 = await db_session.get(Recording, UUID(rec3["id"]))
    assert r3.deleted_at is None


@pytest.mark.asyncio
async def test_bulk_restore_restores_multiple_recordings(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Bulk restore should clear deleted_at on all specified recordings."""
    rec1 = await _create_recording(client, auth_headers, title="Bulk Restore 1")
    rec2 = await _create_recording(client, auth_headers, title="Bulk Restore 2")

    # Soft-delete them first
    for rec_id in [rec1["id"], rec2["id"]]:
        await client.delete(f"/api/recordings/{rec_id}", headers=auth_headers)

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec1["id"], rec2["id"]],
            "action": "restore",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 2

    # Verify restored
    for rec_id in [rec1["id"], rec2["id"]]:
        db_session.expire_all()
        r = await db_session.get(Recording, UUID(rec_id))
        assert r.deleted_at is None


@pytest.mark.asyncio
async def test_bulk_move_moves_recordings_to_folder(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Bulk move should assign folder_id to all specified recordings."""
    rec1 = await _create_recording(client, auth_headers, title="Bulk Move 1")
    rec2 = await _create_recording(client, auth_headers, title="Bulk Move 2")
    folder = await _create_folder(client, auth_headers, "Target Folder")

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec1["id"], rec2["id"]],
            "action": "move",
            "folder_id": folder["id"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 2

    # Verify folder assignment
    for rec_id in [rec1["id"], rec2["id"]]:
        db_session.expire_all()
        r = await db_session.get(Recording, UUID(rec_id))
        assert str(r.folder_id) == folder["id"]


@pytest.mark.asyncio
async def test_bulk_move_to_null_unassigns_folder(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Bulk move with null folder_id should unassign recordings from folders."""
    folder = await _create_folder(client, auth_headers, "Source Folder")
    rec = await _create_recording(client, auth_headers, title="Has Folder")

    # Assign to folder first
    await client.patch(
        f"/api/recordings/{rec['id']}",
        headers=auth_headers,
        json={"folder_id": folder["id"]},
    )

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec["id"]],
            "action": "move",
            "folder_id": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["processed"] == 1

    db_session.expire_all()
    r = await db_session.get(Recording, UUID(rec["id"]))
    assert r.folder_id is None


@pytest.mark.asyncio
async def test_bulk_skips_other_users_recordings(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    """Bulk operation should skip recordings owned by other users."""
    # Create recording as default user
    own_rec = await _create_recording(client, auth_headers, title="My Rec")

    # Create another user and recording
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": "bulk.other@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {reg_resp.json()['access_token']}"}
    other_rec = await _create_recording(client, other_headers, title="Other Rec")

    # Try to bulk delete both
    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [own_rec["id"], other_rec["id"]],
            "action": "delete",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1
    assert payload["failed"] == 1

    # Own recording should be deleted
    db_session.expire_all()
    r1 = await db_session.get(Recording, UUID(own_rec["id"]))
    assert r1.deleted_at is not None

    # Other's recording should be untouched
    r2 = await db_session.get(Recording, UUID(other_rec["id"]))
    assert r2.deleted_at is None


@pytest.mark.asyncio
async def test_bulk_rejects_empty_recording_ids(
    client: AsyncClient, auth_headers: dict
):
    """Bulk operation with empty recording_ids should return 422."""
    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={"recording_ids": [], "action": "delete"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_rejects_invalid_action(
    client: AsyncClient, auth_headers: dict
):
    """Bulk operation with invalid action should return 422."""
    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={"recording_ids": [str(uuid4())], "action": "explode"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_requires_auth(client: AsyncClient):
    """Bulk operation without auth should return 401."""
    response = await client.post(
        "/api/recordings/bulk",
        json={"recording_ids": [str(uuid4())], "action": "delete"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bulk_move_rejects_invalid_folder(
    client: AsyncClient, auth_headers: dict
):
    """Bulk move with non-existent folder should return 404."""
    rec = await _create_recording(client, auth_headers, title="Move Test")

    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={
            "recording_ids": [rec["id"]],
            "action": "move",
            "folder_id": str(uuid4()),
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bulk_rejects_malformed_uuids(
    client: AsyncClient, auth_headers: dict
):
    """Bulk operation with malformed UUIDs should return 422."""
    response = await client.post(
        "/api/recordings/bulk",
        headers=auth_headers,
        json={"recording_ids": ["not-a-uuid"], "action": "delete"},
    )
    assert response.status_code == 422
