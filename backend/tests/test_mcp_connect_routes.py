"""Route tests for one-tap agent-connect provisioning (P0c)."""

import pytest
from sqlalchemy import select

from app.models.api_key import ApiKey

pytestmark = pytest.mark.asyncio


async def test_list_clients(client, auth_headers) -> None:
    resp = await client.get("/api/mcp/connect/clients", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = {c["id"] for c in data["clients"]}
    assert {"openclaw", "hermes", "cursor"} <= ids
    assert data["mcp_url"].endswith("/mcp")


async def test_provision_openclaw_readwrite_mints_and_verifies(
    client, auth_headers, db_session
) -> None:
    resp = await client.post(
        "/api/mcp/connect/provision",
        json={"client": "openclaw", "mode": "readwrite"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token"].startswith("wc_live_")
    assert data["smoke_test"]["ok"] is True  # verified server-side at setup
    assert data["token"] in data["install_command"]
    assert data["token"] in data["config"]
    assert data["deeplink"] is None  # OpenClaw has no OS deeplink
    # Persisted with read + memory:write scope under the client's name.
    keys = (
        await db_session.execute(select(ApiKey).where(ApiKey.name == "OpenClaw"))
    ).scalars().all()
    assert keys and "memory:write" in (keys[0].scopes or [])


async def test_provision_read_mode_has_no_write_scope(client, auth_headers, db_session) -> None:
    resp = await client.post(
        "/api/mcp/connect/provision",
        json={"client": "hermes", "mode": "read"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["smoke_test"]["ok"] is True
    keys = (
        await db_session.execute(select(ApiKey).where(ApiKey.name == "Hermes"))
    ).scalars().all()
    assert keys and "memory:write" not in (keys[0].scopes or [])


async def test_provision_cursor_is_oauth_tokenless(client, auth_headers) -> None:
    resp = await client.post(
        "/api/mcp/connect/provision",
        json={"client": "cursor", "mode": "read"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token"] is None  # OAuth client — no token minted
    assert data["deeplink"].startswith("cursor://")


async def test_provision_unknown_client_404(client, auth_headers) -> None:
    resp = await client.post(
        "/api/mcp/connect/provision",
        json={"client": "nope", "mode": "read"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_provision_requires_session(client) -> None:
    resp = await client.post(
        "/api/mcp/connect/provision",
        json={"client": "openclaw", "mode": "read"},
    )
    assert resp.status_code in (401, 403)
