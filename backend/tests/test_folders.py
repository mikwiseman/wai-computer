"""Tests for folder CRUD endpoints."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


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
