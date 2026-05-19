"""Tests for the WaiComputer MCP OAuth surface."""

import base64
import hashlib
import re
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, quote, urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.mcp_oauth import override_mcp_db_context, reset_mcp_db_context
from app.core.mcp_tools import fetch_recording_for_mcp, search_recordings_for_mcp
from app.mcp_server import create_mcp_app


@pytest_asyncio.fixture(autouse=True)
async def use_test_db_for_mcp_provider(db_session: AsyncSession):
    @asynccontextmanager
    async def context():
        yield db_session

    token = override_mcp_db_context(context)
    try:
        yield
    finally:
        reset_mcp_db_context(token)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _register_oauth_client(client: AsyncClient) -> dict:
    response = await client.post(
        "/register",
        json={
            "redirect_uris": ["http://127.0.0.1:8123/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp:read",
            "client_name": "Test MCP Client",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_mcp_metadata_and_unauthenticated_challenge(client: AsyncClient) -> None:
    settings = get_settings()

    metadata_response = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert metadata_response.status_code == 200
    metadata = metadata_response.json()
    assert metadata["resource"] == settings.mcp_resource_url_resolved
    assert [url.rstrip("/") for url in metadata["authorization_servers"]] == [
        settings.mcp_issuer_url_resolved
    ]
    assert metadata["scopes_supported"] == ["mcp:read"]

    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401
    authenticate = response.headers["www-authenticate"]
    assert "Bearer" in authenticate
    assert "resource_metadata" in authenticate


@pytest.mark.asyncio
async def test_mcp_oauth_consent_and_token_exchange(
    client: AsyncClient,
    auth_headers: dict,
) -> None:
    settings = get_settings()
    oauth_client = await _register_oauth_client(client)
    verifier = "unit-test-verifier-which-is-long-enough"
    redirect_uri = oauth_client["redirect_uris"][0]

    authorize_response = await client.get(
        "/authorize"
        f"?response_type=code"
        f"&client_id={oauth_client['client_id']}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        f"&scope=mcp%3Aread"
        f"&state=test-state"
        f"&resource={quote(settings.mcp_resource_url_resolved, safe='')}"
        f"&code_challenge={_pkce_challenge(verifier)}"
        f"&code_challenge_method=S256",
        follow_redirects=False,
    )
    assert authorize_response.status_code == 302
    consent_location = authorize_response.headers["location"]
    assert consent_location.startswith("/api/mcp/oauth/consent?request=")

    client.cookies.clear()
    anonymous_consent = await client.get(consent_location, follow_redirects=False)
    assert anonymous_consent.status_code == 302
    login_location = anonymous_consent.headers["location"]
    assert login_location.startswith(f"{settings.frontend_url}/login?returnTo=")

    consent_page = await client.get(consent_location, headers=auth_headers)
    assert consent_page.status_code == 200
    assert "Test MCP Client" in consent_page.text
    assert redirect_uri in consent_page.text
    csrf_match = re.search(r'name="csrf" value="([^"]+)"', consent_page.text)
    assert csrf_match is not None

    approval_response = await client.post(
        "/api/mcp/oauth/consent",
        data={
            "request": parse_qs(urlparse(consent_location).query)["request"][0],
            "csrf": csrf_match.group(1),
            "decision": "approve",
        },
        headers=auth_headers,
        follow_redirects=False,
    )
    assert approval_response.status_code == 302
    redirect = urlparse(approval_response.headers["location"])
    assert redirect.geturl().startswith(redirect_uri)
    redirect_query = parse_qs(redirect.query)
    assert redirect_query["state"] == ["test-state"]
    code = redirect_query["code"][0]

    token_response = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_client["client_id"],
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "resource": settings.mcp_resource_url_resolved,
        },
    )
    assert token_response.status_code == 200, token_response.text
    tokens = token_response.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["scope"] == "mcp:read"

    fresh_mcp_app = create_mcp_app(settings)
    async with fresh_mcp_app.router.lifespan_context(fresh_mcp_app):
        transport = ASGITransport(app=fresh_mcp_app)
        async with AsyncClient(transport=transport, base_url="http://localhost:3000") as mcp:
            tools_response = await mcp.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers={
                    "Authorization": f"Bearer {tokens['access_token']}",
                    "Accept": "application/json, text/event-stream",
                },
            )
    assert tools_response.status_code == 200, tools_response.text
    tool_names = {tool["name"] for tool in tools_response.json()["result"]["tools"]}
    assert tool_names == {
        "search",
        "fetch",
        "list_folders",
        "list_recordings",
        "list_action_items",
    }


@pytest.mark.asyncio
async def test_mcp_search_and_fetch_are_user_scoped(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
) -> None:
    first = await client.post(
        "/api/recordings",
        json={"title": "Roadmap sync", "type": "meeting"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    first_recording_id = first.json()["id"]
    transcript = await client.post(
        f"/api/recordings/{first_recording_id}/transcript",
        json={
            "segments": [
                    {
                        "speaker": "Mik",
                        "text": "Discussed the connector roadmap and MCP authorization.",
                        "start_ms": 0,
                        "end_ms": 5000,
                    }
                ],
                "duration_seconds": 5,
            },
            headers=auth_headers,
        )
    assert transcript.status_code == 200, transcript.text

    other_headers_response = await client.post(
        "/api/auth/register",
        json={"email": "other-mcp-user@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other_headers_response.json()['access_token']}"}
    second = await client.post(
        "/api/recordings",
        json={"title": "Private unrelated note", "type": "note"},
        headers=other_headers,
    )
    assert second.status_code == 201, second.text
    other_recording_id = second.json()["id"]

    me_response = await client.get("/api/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    user_id = me_response.json()["id"]
    results = await search_recordings_for_mcp(db_session, user_id, "connector", limit=10)
    assert [item["id"] for item in results["results"]] == [first_recording_id]
    assert "MCP authorization" in results["results"][0]["text"]

    fetched = await fetch_recording_for_mcp(db_session, user_id, first_recording_id)
    assert fetched is not None
    assert fetched["id"] == first_recording_id
    assert "connector roadmap" in fetched["text"]

    assert await fetch_recording_for_mcp(db_session, user_id, other_recording_id) is None
