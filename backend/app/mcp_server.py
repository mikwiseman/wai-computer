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
from app.core.mcp_tools import (
    fetch_recording_for_mcp,
    list_action_items_for_mcp,
    list_folders_for_mcp,
    list_recordings_for_mcp,
    search_recordings_for_mcp,
)
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


_INSTRUCTIONS = """\
Read-only access to the authenticated user's WaiComputer library.

Recordings are organised into folders. Each recording has a transcript, an
AI-generated summary with key points, and structured action items.

Tools:
- search(query, limit=10, folder_ids=None): citation-friendly search across
  recording titles, transcripts, and summaries. Use this first when the user
  asks "what did I say / decide / agree about X". Pass folder_ids to scope
  the search to specific folders.
- fetch(id): the full document for one recording — summary, key points,
  action items, and the diarised transcript. Use after search to read the
  source material in detail.
- list_folders(): the user's folders with non-deleted recording counts. Use
  this to discover folder IDs before calling list_recordings or search with
  folder_ids.
- list_recordings(folder_ids=None, limit=20, cursor=None): browse recordings
  newest-first, optionally scoped to one or more folders. Use this when the
  user wants to "see everything from folder X" rather than text-search.
- list_action_items(status=None, folder_ids=None, limit=20, cursor=None):
  list action items extracted from recordings. Filter by status
  ("pending" / "completed") and/or folder.

See Settings → MCP in any WaiComputer client for setup instructions.
"""


def create_mcp_app(settings: Settings) -> Starlette:
    """Create the authenticated Streamable HTTP MCP application."""
    issuer_url = settings.mcp_issuer_url_resolved
    resource_url = settings.mcp_resource_url_resolved
    client_secret_seconds = settings.mcp_client_secret_expire_days * 24 * 60 * 60

    mcp = FastMCP(
        name="WaiComputer",
        instructions=_INSTRUCTIONS,
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
    async def search(
        query: str,
        limit: int = 10,
        folder_ids: list[str] | None = None,
    ) -> str:
        """Search the authenticated user's WaiComputer recordings.

        Returns up to `limit` matches whose title, transcript segments, or
        summary contain the query string (case-insensitive substring).
        Newest first. Each match has id, title, snippet text, dashboard url,
        and metadata including folder_id, topics, and people_mentioned.

        Use this when the user asks about content, decisions, or quotes — not
        when they want to browse a folder (use list_recordings for that).

        Pass `folder_ids` (a list of UUID strings from list_folders) to
        restrict the search to specific folders. An empty list returns no
        results.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await search_recordings_for_mcp(
                db, user_id, query, limit=limit, folder_ids=folder_ids
            )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def fetch(id: str) -> str:
        """Fetch one authenticated-user WaiComputer recording by id.

        Returns the recording's title, full text (summary + key points +
        action items + diarised transcript), dashboard url, and metadata.
        Text may be truncated for very long recordings; metadata.truncated
        indicates this. Use after `search` or `list_recordings` to read the
        source material in detail.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await fetch_recording_for_mcp(db, user_id, id)
        if result is None:
            raise ValueError("Recording not found")
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def list_folders() -> str:
        """List the user's recording folders with non-deleted counts.

        Returns `{"folders": [{"id", "name", "recording_count"}]}`. IDs are
        UUID strings — pass them to `list_recordings` or `search` as
        `folder_ids` to scope queries. Call this once before any folder-
        filtered query; the list is short (one row per folder).
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await list_folders_for_mcp(db, user_id)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def list_recordings(
        folder_ids: list[str] | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> str:
        """Browse the user's non-deleted recordings, newest first.

        Returns `{"results": [...], "next_cursor": str | None}`. Pass
        `cursor` back unchanged to fetch the next page. `next_cursor` is
        null on the last page.

        Use this when the user wants to enumerate recordings rather than
        text-search them — e.g. "show me the latest from Investors folder"
        or "what did I record last week".

        `folder_ids=None` (default) returns recordings from every folder
        (and unfiled). A non-empty list narrows results to those folders.
        An empty list returns no results.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await list_recordings_for_mcp(
                db, user_id, folder_ids=folder_ids, limit=limit, cursor=cursor
            )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def list_action_items(
        status: str | None = None,
        folder_ids: list[str] | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> str:
        """List action items extracted from the user's recordings.

        Returns `{"results": [...], "next_cursor": str | None}`. Each item
        has task, owner, due_date, priority, status, recording_id,
        recording_title, and url (to the source recording).

        Filter with `status` ("pending", "completed") and/or `folder_ids`.
        Use this when the user asks "what do I need to do" or "what are
        the open commitments from these meetings".
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await list_action_items_for_mcp(
                db,
                user_id,
                status=status,
                folder_ids=folder_ids,
                limit=limit,
                cursor=cursor,
            )
        return json.dumps(result, ensure_ascii=False)

    return mcp.streamable_http_app()
