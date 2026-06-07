"""The ingestion *plan*: how to read all of a tool-based MCP server's data.

A plan is resolved once (at connect, and re-derived when the server's tool set
changes) and persisted on the connection, so each periodic sync is cheap and
deterministic — no LLM on the hot path. Resolution precedence:

    recipe (hand-tuned for known servers)  ->  heuristic (generic)  ->  None

``None`` means "we could not figure out how to read this server" — the caller
turns that into a loud ``needs_setup`` state, never a silent zero-ingest.

A plan is a list of :class:`FetchStep`s. Each step enumerates a collection
(optionally first discovering *scopes* — e.g. Telegram chats — to fan out over),
optionally fetches each row's full content by id, and maps each record to an
``Item`` via a :class:`FieldMap` of candidate JSON paths.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.mcp_tool_classify import (
    ToolRole,
    classify_tool,
    data_noun,
    pagination_param,
    required_id_params,
    singularize,
    tokens,
)

# Default candidate JSON paths for mapping an arbitrary record -> Item fields.
# First non-empty wins. Recipes override these per server.
DEFAULT_TITLE_KEYS = [
    "subject", "title", "name", "summary", "filename", "chat_title",
    "display_name", "displayName", "headline",
]
DEFAULT_BODY_KEYS = [
    "body", "text", "content", "message", "snippet", "plaintext_body",
    "plain_text", "description", "notes", "markdown", "preview",
]
DEFAULT_OCCURRED_KEYS = [
    "occurred_at", "date", "timestamp", "sent_at", "sentDate", "internalDate",
    "created_at", "createdTime", "created_time", "start", "startTime",
    "updated", "updated_at", "modifiedTime", "last_edited_time", "time",
]
DEFAULT_SOURCE_REF_KEYS = [
    "id", "uri", "url", "threadId", "thread_id", "messageId", "message_id",
    "path", "fileId", "file_id", "key", "guid", "uuid",
]
DEFAULT_URL_KEYS = ["url", "link", "webViewLink", "permalink", "htmlLink", "web_url"]


class FieldMap(BaseModel):
    title: list[str] = Field(default_factory=lambda: list(DEFAULT_TITLE_KEYS))
    body: list[str] = Field(default_factory=lambda: list(DEFAULT_BODY_KEYS))
    occurred_at: list[str] = Field(default_factory=lambda: list(DEFAULT_OCCURRED_KEYS))
    source_ref: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCE_REF_KEYS))
    url: list[str] = Field(default_factory=lambda: list(DEFAULT_URL_KEYS))


class CursorSpec(BaseModel):
    """Within-sync pagination: how to walk pages of one enumerate call."""

    page_param: str | None = None      # request arg carrying the page cursor
    next_path: str | None = None       # response path holding the next cursor
    page_size_param: str | None = None
    page_size: int = 50


class FetchStep(BaseModel):
    """One enumerate(->fetch)->map pipeline for a collection on the server."""

    enumerate_tool: str
    enumerate_args: dict = Field(default_factory=dict)
    record_path: str | None = None     # path to the array of rows in the output
    id_path: str | None = None         # path to each row's id (for the fetch step)
    fetch_tool: str | None = None      # None => enumerate rows are already records
    fetch_arg: str | None = None       # param the id is injected into for fetch
    fetch_record_path: str | None = None
    cursor: CursorSpec | None = None
    kind: str = "mcp_item"
    field_map: FieldMap = Field(default_factory=FieldMap)
    # Scope discovery: some enumerate tools need a parent id (Telegram chats ->
    # get_chat_messages(chat_id)). scope_tool enumerates the scopes; scope_arg
    # is the enumerate param the scope id is injected into.
    scope_tool: str | None = None
    scope_id_path: str | None = None
    scope_arg: str | None = None


class IngestionPlan(BaseModel):
    strategy: str = "tools"            # tools | resources
    steps: list[FetchStep] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    planned_by: str = "heuristic"      # recipe | heuristic | llm


class McpToolDescriptor(BaseModel):
    """A normalized view of one advertised tool (from McpClient.introspect)."""

    name: str
    description: str | None = None
    input_schema: dict | None = None
    annotations: dict | None = None


# ── kind inference ────────────────────────────────────────────────────────
_KIND_BY_NOUN = {
    "thread": "email", "mail": "email", "email": "email", "inbox": "email",
    "message": "message", "chat": "message", "dm": "message", "conversation": "message",
    "event": "event", "calendar": "event", "meeting": "event",
    "file": "file", "doc": "file", "document": "file", "drive": "file", "attachment": "file",
    "note": "note", "page": "note", "wiki": "note", "memo": "note",
    "draft": "email", "digest": "message",
}


def infer_kind(enumerate_tool: str, fetch_tool: str | None = None) -> str:
    for name in (fetch_tool or "", enumerate_tool):
        for tok in tokens(name):
            noun = singularize(tok)
            if noun in _KIND_BY_NOUN:
                return _KIND_BY_NOUN[noun]
    return "mcp_item"


def _pair_fetch(enum_name: str, fetch_tools: list[McpToolDescriptor]) -> McpToolDescriptor | None:
    """Find the fetch tool that retrieves one row of the enumerate's collection."""
    noun = data_noun(enum_name)
    if not noun:
        return None
    for ft in fetch_tools:
        ftoks = {singularize(t) for t in tokens(ft.name)}
        if noun in ftoks:
            return ft
    return None


def _cursor_for(schema: dict | None) -> CursorSpec | None:
    page_param = pagination_param(schema)
    if not page_param:
        return None
    # Response next-cursor field is inferred at execution time from the payload;
    # store the common candidates as a hint via next_path left None (the executor
    # scans known names). page_size param detection:
    size_param = None
    props = (schema or {}).get("properties", {}) if isinstance(schema, dict) else {}
    for p in props:
        pl = p.replace("_", "").lower()
        if pl in {"pagesize", "limit", "maxresults", "count", "perpage", "top"}:
            size_param = p
            break
    return CursorSpec(page_param=page_param, page_size_param=size_param)


def resolve_plan_from_tools(tools_desc: list[McpToolDescriptor]) -> IngestionPlan | None:
    """Heuristic plan: classify tools, build one step per enumerate collection.

    Returns ``None`` if no enumerate tool can be found (caller -> needs_setup).
    """
    enum_tools: list[McpToolDescriptor] = []
    fetch_tools: list[McpToolDescriptor] = []
    for t in tools_desc:
        role = classify_tool(t.name, t.input_schema, t.annotations)
        if role is ToolRole.ENUMERATE:
            enum_tools.append(t)
        elif role is ToolRole.FETCH:
            fetch_tools.append(t)

    if not enum_tools:
        return None

    steps: list[FetchStep] = []
    used: set[str] = set()
    for et in enum_tools:
        # Skip an enumerate tool that requires an id-shaped param we can't fill
        # generically (recipe territory, e.g. get_chat_messages(chat_id)). The
        # heuristic only drives self-serve enumerates.
        if required_id_params(et.input_schema):
            continue
        fetch = _pair_fetch(et.name, fetch_tools)
        fetch_arg = None
        if fetch:
            fetch_ids = required_id_params(fetch.input_schema)
            fetch_arg = fetch_ids[0] if fetch_ids else None
        step = FetchStep(
            enumerate_tool=et.name,
            cursor=_cursor_for(et.input_schema),
            fetch_tool=fetch.name if fetch else None,
            fetch_arg=fetch_arg,
            id_path=None,  # executor resolves id from the record via field_map.source_ref
            kind=infer_kind(et.name, fetch.name if fetch else None),
        )
        steps.append(step)
        used.add(et.name)
        if fetch:
            used.add(fetch.name)

    if not steps:
        return None
    return IngestionPlan(
        strategy="tools", steps=steps, tools_used=sorted(used), planned_by="heuristic"
    )


def plan_tools(plan: IngestionPlan) -> set[str]:
    """Every tool a plan will call — the read-only allow-list to enforce."""
    names: set[str] = set()
    for step in plan.steps:
        names.add(step.enumerate_tool)
        if step.fetch_tool:
            names.add(step.fetch_tool)
        if step.scope_tool:
            names.add(step.scope_tool)
    return names
