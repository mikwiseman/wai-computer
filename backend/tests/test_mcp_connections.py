"""Tests for the user-facing MCP connection management API.

These endpoints let a user see which MCP clients they've connected (approved via
OAuth) and revoke any of them from wai.computer — the gap that previously forced
"revoke from the client itself".
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.mcp_oauth import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    override_mcp_db_context,
    reset_mcp_db_context,
    resolve_mcp_access_token_user_id,
    token_hash,
)
from app.models.mcp_oauth import McpOAuthClient, McpOAuthConsent, McpOAuthToken
from tests.conftest import LEGAL_ACCEPTANCE


@pytest_asyncio.fixture(autouse=True)
async def use_test_db_for_mcp_provider(db_session: AsyncSession):
    """Route resolve_mcp_access_token_user_id() through the test session."""

    @asynccontextmanager
    async def context():
        yield db_session

    token = override_mcp_db_context(context)
    try:
        yield
    finally:
        reset_mcp_db_context(token)


async def _seed_connection(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    client_id: str = "bot-client",
    client_name: str = "Meeting Bot",
    access_token: str = "bot-access-token",
    refresh_token: str = "bot-refresh-token",
) -> None:
    """Seed an approved MCP client with a live access + refresh token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    db.add(
        McpOAuthClient(
            client_id=client_id,
            client_secret=None,
            redirect_uris=["http://127.0.0.1:8123/callback"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="mcp:read",
            client_name=client_name,
        )
    )
    db.add(
        McpOAuthConsent(
            user_id=user_id,
            client_id=client_id,
            scopes=["mcp:read"],
            approved_at=now,
        )
    )
    db.add(
        McpOAuthToken(
            token_hash=token_hash(access_token),
            token_type=ACCESS_TOKEN_TYPE,
            client_id=client_id,
            user_id=user_id,
            scopes=["mcp:read"],
            resource=settings.mcp_resource_url_resolved,
            expires_at=now + timedelta(hours=1),
        )
    )
    db.add(
        McpOAuthToken(
            token_hash=token_hash(refresh_token),
            token_type=REFRESH_TOKEN_TYPE,
            client_id=client_id,
            user_id=user_id,
            scopes=["mcp:read"],
            resource=settings.mcp_resource_url_resolved,
            expires_at=now + timedelta(days=90),
        )
    )
    await db.commit()


async def _current_user_id(client: AsyncClient, auth_headers: dict) -> uuid.UUID:
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()["id"])


@pytest.mark.asyncio
async def test_list_connections_returns_connected_clients(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    await _seed_connection(db_session, user_id=user_id)

    response = await client.get("/api/mcp/oauth/connections", headers=auth_headers)
    assert response.status_code == 200, response.text
    connections = response.json()
    assert len(connections) == 1
    connection = connections[0]
    assert connection["client_id"] == "bot-client"
    assert connection["client_name"] == "Meeting Bot"
    assert connection["scopes"] == ["mcp:read"]
    assert connection["approved_at"]
    assert connection["last_active_at"] is not None


@pytest.mark.asyncio
async def test_list_connections_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/mcp/oauth/connections")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_revoke_connection_disables_consent_and_tokens(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
) -> None:
    user_id = await _current_user_id(client, auth_headers)
    await _seed_connection(db_session, user_id=user_id, access_token="bot-access-token")

    # The bot's access token authenticates before revocation.
    assert await resolve_mcp_access_token_user_id("bot-access-token") == user_id

    revoke = await client.post(
        "/api/mcp/oauth/connections/bot-client/revoke", headers=auth_headers
    )
    assert revoke.status_code == 204, revoke.text

    # It disappears from the list and its token no longer authenticates.
    listing = await client.get("/api/mcp/oauth/connections", headers=auth_headers)
    assert listing.json() == []
    assert await resolve_mcp_access_token_user_id("bot-access-token") is None


@pytest.mark.asyncio
async def test_revoke_unknown_connection_returns_404(
    client: AsyncClient,
    auth_headers: dict,
) -> None:
    response = await client.post(
        "/api/mcp/oauth/connections/does-not-exist/revoke", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_connections_are_user_scoped(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
) -> None:
    owner_id = await _current_user_id(client, auth_headers)
    await _seed_connection(
        db_session, user_id=owner_id, client_id="a-client", client_name="A bot"
    )

    other = await client.post(
        "/api/auth/register",
        json={
            "email": f"other-{uuid4().hex}@example.com",
            "password": "password123",
            **LEGAL_ACCEPTANCE,
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    # Another user neither sees nor can revoke the owner's connection.
    other_list = await client.get("/api/mcp/oauth/connections", headers=other_headers)
    assert other_list.json() == []
    other_revoke = await client.post(
        "/api/mcp/oauth/connections/a-client/revoke", headers=other_headers
    )
    assert other_revoke.status_code == 404

    owner_list = await client.get("/api/mcp/oauth/connections", headers=auth_headers)
    assert len(owner_list.json()) == 1
