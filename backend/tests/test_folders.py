"""Tests for folder CRUD endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_user(client: AsyncClient, email: str | None = None) -> dict:
    """Register a new user and return auth headers."""
    email = email or f"folder-test-{uuid4().hex}@example.com"
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "testpassword123"}
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_folder(client: AsyncClient, headers: dict, name: str = "Folder") -> dict:
    resp = await client.post("/api/folders", json={"name": name}, headers=headers)
    assert resp.status_code == 201
    return resp.json()


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Note",
    folder_id: str | None = None,
) -> dict:
    payload: dict = {"title": title, "type": "note"}
    if folder_id is not None:
        payload["folder_id"] = folder_id
    resp = await client.post("/api/recordings", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Original tests
# ---------------------------------------------------------------------------


async def test_list_folders_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/folders", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_folder(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/folders", json={"name": "Work"}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Work"
    assert "id" in data
    assert "created_at" in data


async def test_create_folder_strips_whitespace(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/folders", json={"name": "  Trimmed  "}, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Trimmed"


async def test_create_folder_empty_name_rejected(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/folders", json={"name": "   "}, headers=auth_headers)
    assert resp.status_code == 422


async def test_list_folders_returns_created(client: AsyncClient, auth_headers: dict):
    await client.post("/api/folders", json={"name": "Alpha"}, headers=auth_headers)
    await client.post("/api/folders", json={"name": "Beta"}, headers=auth_headers)

    resp = await client.get("/api/folders", headers=auth_headers)
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()]
    assert "Alpha" in names
    assert "Beta" in names


async def test_rename_folder(client: AsyncClient, auth_headers: dict):
    create_resp = await client.post(
        "/api/folders", json={"name": "Old Name"}, headers=auth_headers
    )
    folder_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/folders/{folder_id}", json={"name": "New Name"}, headers=auth_headers
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "New Name"


async def test_rename_nonexistent_folder_404(client: AsyncClient, auth_headers: dict):
    resp = await client.patch(
        "/api/folders/00000000-0000-0000-0000-000000000000",
        json={"name": "Nope"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_delete_folder(client: AsyncClient, auth_headers: dict):
    create_resp = await client.post(
        "/api/folders", json={"name": "To Delete"}, headers=auth_headers
    )
    folder_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/folders/{folder_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    # Verify gone from list
    list_resp = await client.get("/api/folders", headers=auth_headers)
    ids = [f["id"] for f in list_resp.json()]
    assert folder_id not in ids


async def test_delete_nonexistent_folder_404(client: AsyncClient, auth_headers: dict):
    resp = await client.delete(
        "/api/folders/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_delete_folder_unassigns_recordings(client: AsyncClient, auth_headers: dict):
    # Create folder
    folder_resp = await client.post(
        "/api/folders", json={"name": "Temp"}, headers=auth_headers
    )
    folder_id = folder_resp.json()["id"]

    # Create recording in that folder
    rec_resp = await client.post(
        "/api/recordings",
        json={"title": "In folder", "type": "note", "folder_id": folder_id},
        headers=auth_headers,
    )
    assert rec_resp.status_code == 201
    rec_id = rec_resp.json()["id"]

    # Delete folder
    await client.delete(f"/api/folders/{folder_id}", headers=auth_headers)

    # Recording still exists but folder_id is None
    get_resp = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["folder_id"] is None


# ---------------------------------------------------------------------------
# New coverage tests — targeting lines 55, 68, 82-89, 104-112
# ---------------------------------------------------------------------------


async def test_create_multiple_folders_with_distinct_names(client: AsyncClient, auth_headers: dict):
    """Creating multiple folders with distinct names should succeed."""
    f1 = await _create_folder(client, auth_headers, name="Meetings")
    f2 = await _create_folder(client, auth_headers, name="Projects")
    assert f1["id"] != f2["id"]
    assert f1["name"] == "Meetings"
    assert f2["name"] == "Projects"

    list_resp = await client.get("/api/folders", headers=auth_headers)
    assert list_resp.status_code == 200
    names = [f["name"] for f in list_resp.json()]
    assert "Meetings" in names
    assert "Projects" in names


async def test_rename_folder_persists_in_list(client: AsyncClient, auth_headers: dict):
    """Rename a folder and verify the new name appears in the list (lines 82-89, 55)."""
    folder = await _create_folder(client, auth_headers, name="Draft")

    patch_resp = await client.patch(
        f"/api/folders/{folder['id']}", json={"name": "Final"}, headers=auth_headers
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Final"
    assert patch_resp.json()["id"] == folder["id"]

    # Confirm the rename is reflected in list_folders
    list_resp = await client.get("/api/folders", headers=auth_headers)
    names = [f["name"] for f in list_resp.json()]
    assert "Final" in names
    assert "Draft" not in names


async def test_rename_folder_with_empty_name_rejected(client: AsyncClient, auth_headers: dict):
    """Rename to empty/whitespace name should be rejected by validator."""
    folder = await _create_folder(client, auth_headers, name="Valid")

    resp = await client.patch(
        f"/api/folders/{folder['id']}", json={"name": "   "}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_move_recording_to_folder_via_update(client: AsyncClient, auth_headers: dict):
    """Create a recording without a folder, then move it into one."""
    folder = await _create_folder(client, auth_headers, name="Archive")
    recording = await _create_recording(client, auth_headers, title="Loose note")

    assert recording["folder_id"] is None

    # Move recording into folder via PATCH
    move_resp = await client.patch(
        f"/api/recordings/{recording['id']}",
        json={"folder_id": folder["id"]},
        headers=auth_headers,
    )
    assert move_resp.status_code == 200
    assert move_resp.json()["folder_id"] == folder["id"]


async def test_delete_folder_with_multiple_recordings_unassigns_all(
    client: AsyncClient, auth_headers: dict
):
    """Deleting a folder with multiple recordings sets all folder_ids to None (lines 104-112)."""
    folder = await _create_folder(client, auth_headers, name="Bulk")
    rec1 = await _create_recording(client, auth_headers, title="Rec 1", folder_id=folder["id"])
    rec2 = await _create_recording(client, auth_headers, title="Rec 2", folder_id=folder["id"])
    rec3 = await _create_recording(client, auth_headers, title="Rec 3", folder_id=folder["id"])

    del_resp = await client.delete(f"/api/folders/{folder['id']}", headers=auth_headers)
    assert del_resp.status_code == 204

    # All recordings survive with folder_id cleared
    for rec_id in [rec1["id"], rec2["id"], rec3["id"]]:
        resp = await client.get(f"/api/recordings/{rec_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["folder_id"] is None


async def test_other_user_cannot_see_folders(client: AsyncClient):
    """User A's folders are invisible to User B (list returns empty)."""
    user_a = await _register_user(client)
    user_b = await _register_user(client)

    await _create_folder(client, user_a, name="Private")

    # User B should see no folders
    resp = await client.get("/api/folders", headers=user_b)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_other_user_cannot_rename_folder(client: AsyncClient):
    """User B gets 404 when trying to rename User A's folder (lines 82-89 not-found path)."""
    user_a = await _register_user(client)
    user_b = await _register_user(client)

    folder = await _create_folder(client, user_a, name="Mine")

    resp = await client.patch(
        f"/api/folders/{folder['id']}", json={"name": "Stolen"}, headers=user_b
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Folder not found"


async def test_other_user_cannot_delete_folder(client: AsyncClient):
    """User B gets 404 when trying to delete User A's folder (lines 104-112 not-found path)."""
    user_a = await _register_user(client)
    user_b = await _register_user(client)

    folder = await _create_folder(client, user_a, name="Secret")

    resp = await client.delete(f"/api/folders/{folder['id']}", headers=user_b)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Folder not found"

    # Folder still exists for user A
    list_resp = await client.get("/api/folders", headers=user_a)
    assert len(list_resp.json()) == 1


async def test_list_folders_sorted_alphabetically(client: AsyncClient, auth_headers: dict):
    """Folders are returned sorted by name ascending (line 55)."""
    await _create_folder(client, auth_headers, name="Zebra")
    await _create_folder(client, auth_headers, name="Apple")
    await _create_folder(client, auth_headers, name="Mango")

    resp = await client.get("/api/folders", headers=auth_headers)
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()]
    assert names == ["Apple", "Mango", "Zebra"]
