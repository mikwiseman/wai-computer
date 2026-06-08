"""Tests for read-only API keys (Personal Access Tokens).

A `wc_live_` token is the headless machine-to-machine credential: it authenticates
the REST API and `/mcp` as Bearer, is read-only (safe HTTP methods only), and is
managed only from a real session (a token can't mint/list/revoke tokens).
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.mcp_oauth import override_mcp_db_context, reset_mcp_db_context
from app.mcp_server import create_mcp_app
from app.models.recording import Recording
from tests.conftest import LEGAL_ACCEPTANCE


@pytest_asyncio.fixture(autouse=True)
async def use_test_db_for_mcp_provider(db_session: AsyncSession):
    """Route the MCP provider's token verification through the test session."""

    @asynccontextmanager
    async def context():
        yield db_session

    token = override_mcp_db_context(context)
    try:
        yield
    finally:
        reset_mcp_db_context(token)


async def _create_key(
    client: AsyncClient,
    auth_headers: dict,
    *,
    name: str = "CI bot",
    expires_at: str | None = None,
    allow_memory_write: bool = False,
) -> dict:
    body: dict = {"name": name}
    if expires_at is not None:
        body["expires_at"] = expires_at
    if allow_memory_write:
        body["allow_memory_write"] = True
    response = await client.post("/api/api-keys", json=body, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_create_returns_plaintext_once_then_listed_without_token(
    client: AsyncClient, auth_headers: dict
) -> None:
    created = await _create_key(client, auth_headers, name="Meeting Bot")
    assert created["token"].startswith("wc_live_")
    assert created["name"] == "Meeting Bot"
    assert created["scopes"] == ["read"]
    assert created["prefix"].startswith("wc_live_")
    assert created["last4"] == created["token"][-4:]

    listed = await client.get("/api/api-keys", headers=auth_headers)
    assert listed.status_code == 200
    keys = listed.json()
    assert len(keys) == 1
    assert "token" not in keys[0]
    assert keys[0]["prefix"] == created["prefix"]
    assert keys[0]["last4"] == created["last4"]


@pytest.mark.asyncio
async def test_create_requires_a_name(client: AsyncClient, auth_headers: dict) -> None:
    response = await client.post("/api/api-keys", json={"name": "   "}, headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_key_authenticates_get_requests(
    client: AsyncClient, auth_headers: dict
) -> None:
    token = (await _create_key(client, auth_headers))["token"]
    response = await client.get(
        "/api/recordings", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_api_key_cannot_access_agent_or_mac_edge_surfaces(
    client: AsyncClient, auth_headers: dict
) -> None:
    token = (await _create_key(client, auth_headers))["token"]
    headers = {"Authorization": f"Bearer {token}"}

    capabilities = await client.get("/api/agents/capabilities", headers=headers)
    assert capabilities.status_code == 403, capabilities.text

    heartbeat = await client.post(
        "/api/devices/heartbeat",
        headers=auth_headers,
        json={"platform": "macos", "name": "Owner Mac"},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    device_id = heartbeat.json()["device_id"]
    drain = await client.get(f"/api/devices/{device_id}/desktop-actions", headers=headers)
    assert drain.status_code == 403, drain.text


@pytest.mark.asyncio
async def test_api_key_is_read_only(client: AsyncClient, auth_headers: dict) -> None:
    token = (await _create_key(client, auth_headers))["token"]
    response = await client.post(
        "/api/recordings",
        json={"title": "nope", "type": "note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_create_with_memory_write_scope(client: AsyncClient, auth_headers: dict) -> None:
    created = await _create_key(client, auth_headers, name="Agent", allow_memory_write=True)
    assert created["scopes"] == ["read", "memory:write"]

    listed = (await client.get("/api/api-keys", headers=auth_headers)).json()
    assert listed[0]["scopes"] == ["read", "memory:write"]


@pytest.mark.asyncio
async def test_memory_write_key_still_read_only_on_rest(
    client: AsyncClient, auth_headers: dict
) -> None:
    """The write scope unlocks the MCP `remember` tool only — the REST API stays
    read-only for every api key, write scope or not."""
    token = (await _create_key(client, auth_headers, allow_memory_write=True))["token"]
    response = await client.post(
        "/api/recordings",
        json={"title": "nope", "type": "note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_revoked_key_is_rejected(client: AsyncClient, auth_headers: dict) -> None:
    created = await _create_key(client, auth_headers)
    token = created["token"]
    revoke = await client.post(
        f"/api/api-keys/{created['id']}/revoke", headers=auth_headers
    )
    assert revoke.status_code == 204
    response = await client.get(
        "/api/recordings", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_key_is_rejected(client: AsyncClient, auth_headers: dict) -> None:
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    token = (await _create_key(client, auth_headers, expires_at=past))["token"]
    response = await client.get(
        "/api/recordings", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_keys_are_user_scoped(client: AsyncClient, auth_headers: dict) -> None:
    created = await _create_key(client, auth_headers, name="owner key")

    other = await client.post(
        "/api/auth/register",
        json={
            "email": f"other-{uuid4().hex}@example.com",
            "password": "password123",
            **LEGAL_ACCEPTANCE,
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    other_list = await client.get("/api/api-keys", headers=other_headers)
    assert other_list.json() == []
    other_revoke = await client.post(
        f"/api/api-keys/{created['id']}/revoke", headers=other_headers
    )
    assert other_revoke.status_code == 404


@pytest.mark.asyncio
async def test_api_token_cannot_manage_tokens(client: AsyncClient, auth_headers: dict) -> None:
    token = (await _create_key(client, auth_headers))["token"]
    # Listing keys with a token principal is rejected (session-only).
    listed = await client.get("/api/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 403


@pytest.mark.asyncio
async def test_api_key_works_on_mcp_endpoint(
    client: AsyncClient, auth_headers: dict
) -> None:
    token = (await _create_key(client, auth_headers))["token"]
    settings = get_settings()
    fresh_mcp_app = create_mcp_app(settings)
    async with fresh_mcp_app.router.lifespan_context(fresh_mcp_app):
        transport = ASGITransport(app=fresh_mcp_app)
        async with AsyncClient(transport=transport, base_url="http://localhost:3000") as mcp:
            response = await mcp.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                },
            )
    assert response.status_code == 200, response.text
    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert tool_names == {
        "ask",
        "search",
        "fetch",
        "remember",
        "list_folders",
        "list_recordings",
        "list_action_items",
    }


@pytest.mark.asyncio
async def test_recordings_updated_after_filter(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
) -> None:
    older = (
        await client.post(
            "/api/recordings", json={"title": "older", "type": "note"}, headers=auth_headers
        )
    ).json()
    newer = (
        await client.post(
            "/api/recordings", json={"title": "newer", "type": "note"}, headers=auth_headers
        )
    ).json()

    # The test client shares one uncommitted transaction, so all rows get the same
    # now() — set distinct updated_at explicitly to exercise the filter deterministically.
    t_older = datetime(2026, 5, 1, tzinfo=timezone.utc)
    t_newer = t_older + timedelta(hours=1)
    await db_session.execute(
        update(Recording).where(Recording.id == UUID(older["id"])).values(updated_at=t_older)
    )
    await db_session.execute(
        update(Recording).where(Recording.id == UUID(newer["id"])).values(updated_at=t_newer)
    )
    await db_session.flush()

    only_newer = await client.get(
        "/api/recordings", params={"updated_after": t_older.isoformat()}, headers=auth_headers
    )
    assert only_newer.status_code == 200, only_newer.text
    assert [r["id"] for r in only_newer.json()] == [newer["id"]]

    both = await client.get(
        "/api/recordings",
        params={"updated_after": (t_older - timedelta(minutes=1)).isoformat()},
        headers=auth_headers,
    )
    # Ascending order when syncing forward by watermark.
    assert [r["id"] for r in both.json()] == [older["id"], newer["id"]]
