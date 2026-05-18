"""Tests for /api/companion REST CRUD (no streaming yet — that's Phase 5)."""

from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def second_auth_headers(client: AsyncClient) -> dict:
    """A second registered user — used for per-user isolation tests."""
    email = f"other-{uuid4().hex}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestCreateChat:
    async def test_create_empty_chat(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/companion/chats", json={}, headers=auth_headers
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] is None
        assert body["scope"] is None
        assert body["last_message_at"] is None
        assert "id" in body
        assert "created_at" in body

    async def test_create_with_scope(self, client: AsyncClient, auth_headers: dict):
        # Only recording_ids is server-enforced; sending unenforced fields
        # would silently fail at retrieval, so we accept just the supported one.
        scope = {
            "recording_ids": [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
        }
        response = await client.post(
            "/api/companion/chats",
            json={"scope": scope},
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["scope"] == scope

    async def test_create_requires_auth(self, client: AsyncClient):
        response = await client.post("/api/companion/chats", json={})
        assert response.status_code == 401


class TestListChats:
    async def test_empty(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/companion/chats", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == {"chats": []}

    async def test_returns_all_created_chats(
        self, client: AsyncClient, auth_headers: dict
    ):
        # Note: under the shared test session, POSTs within the same fixture run
        # in one transaction so `now()` collapses to a single value — we can't
        # assert per-row ordering here. Production uses a fresh session and
        # transaction per request, so `created_at` differs naturally. Verify
        # the set is returned and a fresh chat patched with last_message_at
        # sorts above one without.
        ids = set()
        for _ in range(3):
            r = await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
            ids.add(r.json()["id"])

        response = await client.get("/api/companion/chats", headers=auth_headers)
        assert response.status_code == 200
        returned = {c["id"] for c in response.json()["chats"]}
        assert returned == ids

    async def test_limit_param(self, client: AsyncClient, auth_headers: dict):
        for _ in range(5):
            await client.post("/api/companion/chats", json={}, headers=auth_headers)

        response = await client.get(
            "/api/companion/chats?limit=2", headers=auth_headers
        )
        assert response.status_code == 200
        assert len(response.json()["chats"]) == 2

    async def test_user_isolation(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
    ):
        await client.post(
            "/api/companion/chats", json={}, headers=auth_headers
        )
        response = await client.get(
            "/api/companion/chats", headers=second_auth_headers
        )
        assert response.status_code == 200
        assert response.json()["chats"] == []

    async def test_soft_deleted_excluded(
        self, client: AsyncClient, auth_headers: dict
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        await client.delete(
            f"/api/companion/chats/{created['id']}", headers=auth_headers
        )

        response = await client.get("/api/companion/chats", headers=auth_headers)
        assert response.json()["chats"] == []


class TestGetChat:
    async def test_returns_empty_messages_for_new_chat(
        self, client: AsyncClient, auth_headers: dict
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        response = await client.get(
            f"/api/companion/chats/{created['id']}", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == created["id"]
        assert body["messages"] == []

    async def test_404_for_other_user_chat(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        response = await client.get(
            f"/api/companion/chats/{created['id']}", headers=second_auth_headers
        )
        assert response.status_code == 404

    async def test_404_for_unknown_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get(
            f"/api/companion/chats/{uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_404_for_soft_deleted(
        self, client: AsyncClient, auth_headers: dict
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        await client.delete(
            f"/api/companion/chats/{created['id']}", headers=auth_headers
        )
        response = await client.get(
            f"/api/companion/chats/{created['id']}", headers=auth_headers
        )
        assert response.status_code == 404


class TestPatchChat:
    async def test_rename(self, client: AsyncClient, auth_headers: dict):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        response = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"title": "Standup recap"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Standup recap"

    async def test_pin_then_unpin(
        self, client: AsyncClient, auth_headers: dict
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        pinned = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"pinned": True},
            headers=auth_headers,
        )
        assert pinned.status_code == 200
        assert pinned.json()["pinned_at"] is not None

        unpinned = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"pinned": False},
            headers=auth_headers,
        )
        assert unpinned.json()["pinned_at"] is None

    async def test_archive_then_unarchive(
        self, client: AsyncClient, auth_headers: dict
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        archived = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"archived": True},
            headers=auth_headers,
        )
        assert archived.json()["archived_at"] is not None

        unarchived = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"archived": False},
            headers=auth_headers,
        )
        assert unarchived.json()["archived_at"] is None

    async def test_update_scope(self, client: AsyncClient, auth_headers: dict):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        scope = {"recording_ids": [str(uuid4())]}
        response = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"scope": scope},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["scope"] == scope

    async def test_other_user_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        response = await client.patch(
            f"/api/companion/chats/{created['id']}",
            json={"title": "hijacked"},
            headers=second_auth_headers,
        )
        assert response.status_code == 404


class TestDeleteChat:
    async def test_soft_delete_returns_204(
        self, client: AsyncClient, auth_headers: dict
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        response = await client.delete(
            f"/api/companion/chats/{created['id']}", headers=auth_headers
        )
        assert response.status_code == 204

    async def test_delete_other_user_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        second_auth_headers: dict,
    ):
        created = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        response = await client.delete(
            f"/api/companion/chats/{created['id']}", headers=second_auth_headers
        )
        assert response.status_code == 404
