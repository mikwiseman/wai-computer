"""Tests for folder endpoints and folder-aware recording filters."""

import pytest
from httpx import AsyncClient


async def _create_folder(client: AsyncClient, headers: dict, name: str = "Projects") -> dict:
    response = await client.post("/api/folders", headers=headers, json={"name": name})
    assert response.status_code == 201
    return response.json()


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str = "Folder Recording",
    folder_id: str | None = None,
) -> dict:
    payload: dict[str, str | None] = {"title": title, "type": "note", "language": "en"}
    if folder_id is not None:
        payload["folder_id"] = folder_id

    response = await client.post("/api/recordings", headers=headers, json=payload)
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_folder_create_list_and_filter_recordings(client: AsyncClient, auth_headers: dict):
    """Folders should be creatable and usable as a recording filter."""
    folder = await _create_folder(client, auth_headers, name="Customer Calls")
    unfiled = await _create_recording(client, auth_headers, title="Loose")
    filed = await _create_recording(client, auth_headers, title="Filed", folder_id=folder["id"])

    list_response = await client.get("/api/folders", headers=auth_headers)
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [folder["id"]]

    folder_response = await client.get(
        "/api/recordings",
        headers=auth_headers,
        params={"folder_id": folder["id"]},
    )
    assert folder_response.status_code == 200
    assert [item["id"] for item in folder_response.json()] == [filed["id"]]

    all_response = await client.get("/api/recordings", headers=auth_headers)
    assert all_response.status_code == 200
    assert {item["id"] for item in all_response.json()} == {filed["id"], unfiled["id"]}


@pytest.mark.asyncio
async def test_delete_folder_clears_recording_folder_id(client: AsyncClient, auth_headers: dict):
    """Deleting a folder should keep recordings but clear their folder assignment."""
    folder = await _create_folder(client, auth_headers, name="Archive")
    recording = await _create_recording(client, auth_headers, folder_id=folder["id"])

    delete_response = await client.delete(f"/api/folders/{folder['id']}", headers=auth_headers)
    assert delete_response.status_code == 204

    detail_response = await client.get(f"/api/recordings/{recording['id']}", headers=auth_headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["folder_id"] is None
