"""API tests for MCP connection management routes.

Introspection (network) and the sync task are stubbed so these run offline.
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio

# A fake introspection result so create() doesn't hit the network.
class _FakeIntro:
    tools = ["search", "fetch"]
    resources = []


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def introspect(self):
        return _FakeIntro()


async def test_create_connection_encrypts_token_and_introspects(client, auth_headers) -> None:
    with patch("app.core.mcp_client.McpClient", _FakeClient):
        resp = await client.post(
            "/api/mcp-connections",
            json={
                "server_label": "My Notes",
                "server_url": "https://mcp.example.com/notes",
                "auth_type": "pat",
                "auth_token": "pat-secret-123",
            },
            headers=auth_headers,
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["has_token"] is True
    # Secret is never returned.
    assert "auth_token" not in data
    assert "pat-secret-123" not in resp.text
    assert data["capabilities"]["tools"] == ["search", "fetch"]
    assert data["allowed_tools"] == []  # resources-only by default


async def test_create_requires_token_for_pat(client, auth_headers) -> None:
    resp = await client.post(
        "/api/mcp-connections",
        json={"server_label": "X", "server_url": "https://x.com/mcp", "auth_type": "pat"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_create_none_auth_needs_no_token(client, auth_headers) -> None:
    with patch("app.core.mcp_client.McpClient", _FakeClient):
        resp = await client.post(
            "/api/mcp-connections",
            json={"server_label": "Pub", "server_url": "https://pub.example.com/mcp"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    assert resp.json()["has_token"] is False


async def test_duplicate_server_url_conflicts(client, auth_headers) -> None:
    payload = {"server_label": "Dup", "server_url": "https://dup.example.com/mcp"}
    with patch("app.core.mcp_client.McpClient", _FakeClient):
        first = await client.post("/api/mcp-connections", json=payload, headers=auth_headers)
        second = await client.post("/api/mcp-connections", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert second.status_code == 409


async def test_list_get_patch_delete_and_sync(client, auth_headers) -> None:
    with patch("app.core.mcp_client.McpClient", _FakeClient):
        created = await client.post(
            "/api/mcp-connections",
            json={"server_label": "L", "server_url": "https://l.example.com/mcp"},
            headers=auth_headers,
        )
    cid = created.json()["id"]

    listing = await client.get("/api/mcp-connections", headers=auth_headers)
    assert listing.status_code == 200
    assert any(c["id"] == cid for c in listing.json())

    # Pause it.
    patched = await client.patch(
        f"/api/mcp-connections/{cid}", json={"enabled": False}, headers=auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["status"] == "paused"

    # Sync of a paused connection is rejected.
    blocked = await client.post(f"/api/mcp-connections/{cid}/sync", headers=auth_headers)
    assert blocked.status_code == 400

    # Resume + sync enqueues.
    await client.patch(
        f"/api/mcp-connections/{cid}", json={"enabled": True}, headers=auth_headers
    )
    with patch("app.tasks.mcp_sync.sync_mcp_connection.delay") as delay:
        synced = await client.post(f"/api/mcp-connections/{cid}/sync", headers=auth_headers)
    assert synced.status_code == 202
    delay.assert_called_once()

    deleted = await client.delete(f"/api/mcp-connections/{cid}", headers=auth_headers)
    assert deleted.status_code == 204
    gone = await client.get(f"/api/mcp-connections/{cid}", headers=auth_headers)
    assert gone.status_code == 404


async def test_connections_scoped_to_user(client, auth_headers) -> None:
    from uuid import uuid4

    with patch("app.core.mcp_client.McpClient", _FakeClient):
        created = await client.post(
            "/api/mcp-connections",
            json={"server_label": "Mine", "server_url": "https://mine.example.com/mcp"},
            headers=auth_headers,
        )
    cid = created.json()["id"]
    other = await client.post(
        "/api/auth/register",
        json={
            "email": f"o-{uuid4().hex}@example.com",
            "password": "testpassword123",
            "accepted_legal_terms": True,
            "legal_terms_version": "2026-05-22",
            "legal_privacy_version": "2026-05-22",
        },
    )
    oh = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await client.get(f"/api/mcp-connections/{cid}", headers=oh)).status_code == 404
