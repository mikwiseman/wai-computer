"""Tests for Collections API (user apps) routes."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


class TestCreateApp:
    async def test_create_app(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/apps",
            json={
                "name": "habits",
                "display_name": "Habit Tracker",
                "description": "Tracks meditation and exercise",
                "icon": "✅",
                "visibility": "private",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "habits"
        assert data["display_name"] == "Habit Tracker"
        assert data["description"] == "Tracks meditation and exercise"
        assert data["icon"] == "✅"
        assert data["status"] == "draft"
        assert data["visibility"] == "private"
        assert data["published_at"] is None
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

    async def test_list_can_filter_live_apps(self, client: AsyncClient, auth_headers: dict):
        create_resp = await client.post(
            "/api/apps",
            json={"name": "tracker", "display_name": "Tracker"},
            headers=auth_headers,
        )
        app_id = create_resp.json()["id"]
        await client.post(
            f"/api/apps/{app_id}/publish",
            json={"visibility": "unlisted", "app_url": "https://tracker.wai.computer"},
            headers=auth_headers,
        )
        await client.post(
            "/api/apps",
            json={"name": "draft-app", "display_name": "Draft App"},
            headers=auth_headers,
        )

        response = await client.get("/api/apps?status=live", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "live"
        assert data[0]["visibility"] == "unlisted"

    async def test_publish_app_marks_it_shareable(self, client: AsyncClient, auth_headers: dict):
        create_resp = await client.post(
            "/api/apps",
            json={"name": "share-me", "display_name": "Share Me"},
            headers=auth_headers,
        )
        app_id = create_resp.json()["id"]

        response = await client.post(
            f"/api/apps/{app_id}/publish",
            json={"visibility": "public", "app_url": "https://share-me.wai.computer"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "live"
        assert data["visibility"] == "public"
        assert data["app_url"] == "https://share-me.wai.computer"
        assert data["published_at"] is not None

    async def test_publish_app_can_promote_preview_to_live(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        create_resp = await client.post(
            "/api/apps",
            json={
                "name": "preview-app",
                "display_name": "Preview App",
                "app_url": "https://preview.preview-app.pages.dev",
                "settings": {
                    "bundle_cache_key": "site:preview-app",
                    "cloudflare_project_name": "wai-site-preview-app",
                    "generated_slug": "preview-app",
                },
            },
            headers=auth_headers,
        )
        app_id = create_resp.json()["id"]

        with patch(
            "app.api.routes.apps.promote_generated_user_app",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "url": "https://wai-site-preview-app.pages.dev",
                    "deployment_mode": "production",
                    "project_name": "wai-site-preview-app",
                }
            ),
        ):
            response = await client.post(
                f"/api/apps/{app_id}/publish",
                json={"visibility": "public"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "live"
        assert data["app_url"] == "https://wai-site-preview-app.pages.dev"

    async def test_list_deployments_and_rollback(self, client: AsyncClient, auth_headers: dict):
        create_resp = await client.post(
            "/api/apps",
            json={
                "name": "rollback-app",
                "display_name": "Rollback App",
                "app_url": "https://wai-site-rollback-app.pages.dev",
                "settings": {
                    "bundle_cache_key": "site:rollback-app:v:current",
                    "cloudflare_project_name": "wai-site-rollback-app",
                    "generated_slug": "rollback-app",
                    "deployment_mode": "preview",
                    "deployment_target": "cloudflare-pages",
                    "bundle_kind": "vite-react-site",
                    "framework": "react-vite",
                    "generation_provider": "claude-code",
                },
            },
            headers=auth_headers,
        )
        app = create_resp.json()

        async def fake_promote(_db, target_app):
            from app.services.user_apps import record_user_app_deployment

            target_app.app_url = "https://wai-site-rollback-app.pages.dev"
            result = {
                "success": True,
                "url": "https://wai-site-rollback-app.pages.dev",
                "deployment_mode": "production",
                "deployment_target": "cloudflare-pages",
                "project_name": "wai-site-rollback-app",
                "bundle_cache_key": "site:rollback-app:v:current",
            }
            await record_user_app_deployment(_db, target_app, result)
            return result

        with patch("app.api.routes.apps.promote_generated_user_app", new=fake_promote):
            publish_resp = await client.post(
                f"/api/apps/{app['id']}/publish",
                json={"visibility": "public"},
                headers=auth_headers,
            )
        assert publish_resp.status_code == 200

        deployments_resp = await client.get(
            f"/api/apps/{app['id']}/deployments",
            headers=auth_headers,
        )
        assert deployments_resp.status_code == 200
        deployments = deployments_resp.json()
        assert len(deployments) >= 1
        deployment_id = deployments[0]["id"]

        with patch(
            "app.services.agent.app_builder.publish_cached_bundle",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "url": "https://wai-site-rollback-app.pages.dev",
                    "deployment_mode": "production",
                    "deployment_target": "cloudflare-pages",
                    "deployment_url": "https://deploy.pages.dev",
                    "project_name": "wai-site-rollback-app",
                    "bundle_cache_key": deployments[0]["bundle_cache_key"],
                    "bundle_kind": "vite-react-site",
                    "framework": "react-vite",
                    "generation_provider": "claude-code",
                }
            ),
        ):
            rollback_resp = await client.post(
                f"/api/apps/{app['id']}/rollback",
                json={"deployment_id": deployment_id, "visibility": "unlisted"},
                headers=auth_headers,
            )

        assert rollback_resp.status_code == 200
        assert rollback_resp.json()["visibility"] == "unlisted"


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
