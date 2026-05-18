"""Remote MCP server mounted into the WaiComputer API."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from starlette.applications import Starlette

from app.config import Settings
from app.core.mcp_oauth import (
    MCP_READ_SCOPE,
    mcp_oauth_provider,
    resolve_mcp_access_token_user_id,
)
from app.core.mcp_tools import fetch_recording_for_mcp, search_recordings_for_mcp
from app.db.session import get_db_context


def _allowed_hosts(settings: Settings) -> list[str]:
    hosts = {"localhost", "127.0.0.1"}
    for value in [
        settings.frontend_url,
        settings.mcp_issuer_url_resolved,
        settings.mcp_resource_url_resolved,
    ]:
        parsed = urlparse(value)
        if parsed.netloc:
            hosts.add(parsed.netloc)
    return sorted(hosts)


def create_mcp_app(settings: Settings) -> Starlette:
    """Create the authenticated Streamable HTTP MCP application."""
    issuer_url = settings.mcp_issuer_url_resolved
    resource_url = settings.mcp_resource_url_resolved
    client_secret_seconds = settings.mcp_client_secret_expire_days * 24 * 60 * 60

    mcp = FastMCP(
        name="WaiComputer",
        instructions=(
            "Read-only access to the authenticated user's WaiComputer library.\n\n"
            "Tools:\n"
            "- search(query, limit=10): citation-friendly search across recordings, "
            "transcripts, summaries, and action items.\n"
            "- fetch(id): full document for a recording, including summary, key points, "
            "action items, and the transcript.\n\n"
            "See Settings → MCP in any WaiComputer client for setup instructions."
        ),
        auth_server_provider=mcp_oauth_provider,
        auth=AuthSettings(
            issuer_url=issuer_url,
            resource_server_url=resource_url,
            required_scopes=[MCP_READ_SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                client_secret_expiry_seconds=client_secret_seconds,
                valid_scopes=[MCP_READ_SCOPE],
                default_scopes=[MCP_READ_SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        transport_security=TransportSecuritySettings(
            allowed_hosts=_allowed_hosts(settings),
            allowed_origins=[settings.frontend_url],
        ),
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

    async def _current_user_id():
        access_token = get_access_token()
        if access_token is None:
            raise ValueError("MCP access token is required")
        user_id = await resolve_mcp_access_token_user_id(access_token.token)
        if user_id is None:
            raise ValueError("MCP access token is invalid")
        return user_id

    @mcp.tool()
    async def search(query: str, limit: int = 10) -> str:
        """Search the authenticated user's WaiComputer recordings."""
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await search_recordings_for_mcp(db, user_id, query, limit=limit)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def fetch(id: str) -> str:
        """Fetch one authenticated-user WaiComputer recording by id."""
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await fetch_recording_for_mcp(db, user_id, id)
        if result is None:
            raise ValueError("Recording not found")
        return json.dumps(result, ensure_ascii=False)

    return mcp.streamable_http_app()
