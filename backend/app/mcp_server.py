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
from app.core.mcp_brain_tools import (
    ask_brain_for_mcp,
    fetch_document_for_mcp,
    remember_for_mcp,
    search_brain_for_mcp,
    wake_up_for_mcp,
)
from app.core.mcp_oauth import (
    MCP_READ_SCOPE,
    MCP_SCOPES,
    MCP_WRITE_SCOPE,
    mcp_oauth_provider,
    resolve_mcp_access_token_user_id,
)
from app.core.mcp_tools import (
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
WaiComputer is the user's second brain — their long-term memory. It holds
voice recordings (transcribed + summarised), saved notes and articles, and
past Wai chats, all linked into one searchable knowledge base. Use it to
recall what the user has captured before answering from your own assumptions.

Tools:
- wake_up(): call ONCE at the start of a session, first. Returns the user's
  profile (durable facts), the folder + top-entity taxonomy for scoping, and the
  usage protocol — cheaply. Then, before asserting anything about the user,
  recall first (ask/search); never guess.
- ask(question): the primary memory tool. Returns ONE cited answer synthesised
  across everything the user has captured — recordings, notes, and chats —
  plus an honest list of gaps and how stale the sources are. Ask it first
  ("what did I decide about X", "what do I know about Y") before falling back
  to raw search. Never invent an answer the brain doesn't support.
- search(query, limit=10, folder_ids=None): unified search across recordings,
  notes, and chats. Each hit has an id (fetchable), a snippet, and
  metadata.source_kind. Pass folder_ids to scope to specific recording folders
  (folders apply to recordings only).
- fetch(id): the full document for one source by id — a recording (summary +
  key points + action items + diarised transcript), a note, or a chat. Use
  after ask/search to read the source material in detail.
- remember(text, title=None, source_url=None): SAVE a new memory back into the
  brain — a fact, decision, or note worth keeping. Only works when this
  connection was granted write access; otherwise it returns a clear error and
  the connection stays read-only. Use it when the user says "remember that…"
  or when you learn a durable fact worth recalling later.
- list_folders(): the user's recording folders with counts. Discover folder
  IDs before a folder-scoped search or list_recordings.
- list_recordings(folder_ids=None, limit=20, cursor=None): browse recordings
  newest-first, optionally scoped to folders.
- list_action_items(status=None, folder_ids=None, limit=20, cursor=None):
  list action items from recordings, filtered by status / folder.

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
                # Write is registerable + requestable, but never default: a
                # client only gets it by explicitly asking for mcp:write.
                valid_scopes=MCP_SCOPES,
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

    async def _current_access():
        """Resolve the authenticated user and the active access token (for scope
        checks). Raises on a missing/invalid token."""
        access_token = get_access_token()
        if access_token is None:
            raise ValueError("MCP access token is required")
        user_id = await resolve_mcp_access_token_user_id(access_token.token)
        if user_id is None:
            raise ValueError("MCP access token is invalid")
        return user_id, access_token

    async def _current_user_id():
        user_id, _ = await _current_access()
        return user_id

    @mcp.tool()
    async def wake_up() -> str:
        """Load the user's profile + brain taxonomy + protocol — call ONCE per session, first.

        Returns `{profile, taxonomy, protocol}`: a compact durable-memory profile
        (~800 tokens) so you boot knowing the user, the folder + top-entity
        taxonomy for scoping `search`, and the recall-before-asserting protocol.
        Cheap (no LLM). Call it at the start of a session before answering anything
        about the user, then prefer `ask` over raw `search`.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await wake_up_for_mcp(db, user_id)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def ask(question: str) -> str:
        """Ask the user's second brain a question and get ONE cited answer.

        Synthesises across everything captured — recordings, notes, and Wai
        chats — and returns `{answer, citations, gaps, freshness}`. Each
        citation has an id (fetchable), source_kind, title, and dashboard url.
        `gaps` states what the brain does not contain; `freshness` says how old
        the newest supporting source is. The answer is grounded in the user's
        own data only — if the brain has nothing, `answer` is empty and `gaps`
        explains. Prefer this over raw `search` when the user wants an answer
        rather than a list of sources.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await ask_brain_for_mcp(db, user_id, question)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def search(
        query: str,
        limit: int = 10,
        folder_ids: list[str] | None = None,
    ) -> str:
        """Search the user's whole brain — recordings, notes, AND chats.

        Returns `{"results": [...]}`, newest-relevant first. Each match has id
        (fetchable via `fetch`), title, snippet text, a dashboard url, and
        `metadata.source_kind` ("recording" | "item" | "chat") so you can tell a
        meeting from a saved note from a Wai chat.

        Use this when the user asks about content, decisions, or quotes and you
        want the raw sources — for a synthesised answer, use `ask` instead.

        Pass `folder_ids` (UUID strings from list_folders) to restrict to
        specific recording folders; folders apply to recordings only, so a
        folder-scoped search returns recordings exclusively. An empty list
        returns no results.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            if folder_ids is not None:
                result = await search_recordings_for_mcp(
                    db, user_id, query, limit=limit, folder_ids=folder_ids
                )
            else:
                result = await search_brain_for_mcp(db, user_id, query, limit=limit)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def fetch(id: str) -> str:
        """Fetch one brain document by id — a recording, note, or chat.

        Returns the source's title, full text, dashboard url, and metadata
        (including `source_kind`). For a recording the text is summary + key
        points + action items + diarised transcript; for a note it's the
        summary + body; for a chat it's the message transcript. Text may be
        truncated for very long sources (metadata.truncated). Use after `ask`,
        `search`, or `list_recordings` to read source material in detail.
        """
        user_id = await _current_user_id()
        async with get_db_context() as db:
            result = await fetch_document_for_mcp(db, user_id, id)
        if result is None:
            raise ValueError("Document not found")
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def remember(
        text: str,
        title: str | None = None,
        source_url: str | None = None,
    ) -> str:
        """Save a new memory into the user's brain (requires write access).

        Stores `text` as a note that flows into the same search + dossier
        pipeline as everything else, so future `ask` / `search` calls can recall
        it. Provide a short `title` and an optional `source_url`. Returns
        `{id, created, title, url}`; `created=false` means an identical memory
        already existed (no duplicate is made).

        This tool only works when the connection was granted memory write
        access — otherwise it returns an error and nothing is saved. Use it when
        the user says "remember that…", or when you learn a durable fact worth
        recalling later. Do not store secrets or transient chatter.
        """
        user_id, access_token = await _current_access()
        if MCP_WRITE_SCOPE not in (access_token.scopes or []):
            raise ValueError(
                "This connection is read-only. Reconnect with memory write "
                "access enabled (Settings → MCP) to save memories."
            )
        async with get_db_context() as db:
            result = await remember_for_mcp(
                db, user_id, text, title=title, source_url=source_url
            )
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
