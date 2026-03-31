"""Tests for Collections API (user apps) routes."""

import pytest
from httpx import AsyncClient


class TestCreateApp:
    async def test_create_app(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/apps",
            json={"name": "habits", "display_name": "Habit Tracker", "icon": "✅"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "habits"
        assert data["display_name"] == "Habit Tracker"
        assert data["icon"] == "✅"
        assert data["item_count"] == 0

    async def test_create_duplicate_app_fails(self, client: AsyncClient, auth_headers: dict):
        await client.post(
            "/api/apps",
            json={"name": "habits", "display_name": "Habits"},
            headers=auth_headers,
        )
        response = await client.post(
            "/api/apps",
            json={"name": "habits", "display_name": "Habits 2"},
            headers=auth_headers,
        )
        assert response.status_code == 409

    async def test_create_app_requires_auth(self, client: AsyncClient):
        response = await client.post(
            "/api/apps",
            json={"name": "test", "display_name": "Test"},
        )
        assert response.status_code == 401


class TestListApps:
    async def test_list_empty(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/apps", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_apps(self, client: AsyncClient, auth_headers: dict):
        await client.post(
            "/api/apps",
            json={"name": "habits", "display_name": "Habits"},
            headers=auth_headers,
        )
        await client.post(
            "/api/apps",
            json={"name": "expenses", "display_name": "Expenses"},
            headers=auth_headers,
        )
        response = await client.get("/api/apps", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


class TestAppItems:
    async def _create_app(self, client, auth_headers):
        resp = await client.post(
            "/api/apps",
            json={"name": "habits", "display_name": "Habits"},
            headers=auth_headers,
        )
        return resp.json()["id"]

    async def test_create_item(self, client: AsyncClient, auth_headers: dict):
        app_id = await self._create_app(client, auth_headers)
        response = await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"habit": "meditation", "completed": True}},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["data"]["habit"] == "meditation"
        assert data["data"]["completed"] is True

    async def test_list_items(self, client: AsyncClient, auth_headers: dict):
        app_id = await self._create_app(client, auth_headers)
        await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"habit": "meditation"}},
            headers=auth_headers,
        )
        await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"habit": "exercise"}},
            headers=auth_headers,
        )
        response = await client.get(f"/api/apps/{app_id}/items", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_update_item(self, client: AsyncClient, auth_headers: dict):
        app_id = await self._create_app(client, auth_headers)
        create_resp = await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"habit": "meditation", "completed": False}},
            headers=auth_headers,
        )
        item_id = create_resp.json()["id"]
        response = await client.patch(
            f"/api/apps/{app_id}/items/{item_id}",
            json={"data": {"habit": "meditation", "completed": True}},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["data"]["completed"] is True

    async def test_delete_item(self, client: AsyncClient, auth_headers: dict):
        app_id = await self._create_app(client, auth_headers)
        create_resp = await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"test": True}},
            headers=auth_headers,
        )
        item_id = create_resp.json()["id"]
        response = await client.delete(
            f"/api/apps/{app_id}/items/{item_id}", headers=auth_headers,
        )
        assert response.status_code == 204

        list_resp = await client.get(f"/api/apps/{app_id}/items", headers=auth_headers)
        assert len(list_resp.json()) == 0

    async def test_item_not_found(self, client: AsyncClient, auth_headers: dict):
        app_id = await self._create_app(client, auth_headers)
        response = await client.patch(
            f"/api/apps/{app_id}/items/00000000-0000-0000-0000-000000000000",
            json={"data": {"test": True}},
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestDeleteApp:
    async def test_delete_cascades_items(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/apps",
            json={"name": "temp", "display_name": "Temp"},
            headers=auth_headers,
        )
        app_id = resp.json()["id"]
        await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"x": 1}},
            headers=auth_headers,
        )
        delete_resp = await client.delete(f"/api/apps/{app_id}", headers=auth_headers)
        assert delete_resp.status_code == 204

        get_resp = await client.get(f"/api/apps/{app_id}", headers=auth_headers)
        assert get_resp.status_code == 404


class TestAppStats:
    async def test_stats(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/apps",
            json={"name": "stats_test", "display_name": "Stats"},
            headers=auth_headers,
        )
        app_id = resp.json()["id"]
        await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"a": 1}},
            headers=auth_headers,
        )
        await client.post(
            f"/api/apps/{app_id}/items",
            json={"data": {"b": 2}},
            headers=auth_headers,
        )
        response = await client.get(f"/api/apps/{app_id}/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 2
        assert data["last_item_at"] is not None
