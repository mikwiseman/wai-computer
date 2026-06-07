"""Deterministic, zero-LLM classification of an MCP server's tools.

The connect-any-MCP ingestion engine has to read data from servers whose data
lives behind *tools* (``search_threads`` / ``get_thread`` / ``list_chats`` /
``read_note`` / ``search_files``), not MCP *resources*. To pull "all the data"
generically we must decide, for each advertised tool, whether it:

- **enumerates** a collection (``list_*`` / ``search_*`` — returns many rows,
  usually paginated), or
- **fetches** one record by id (``get_*`` / ``read_*`` — one id-shaped param), or
- must be **skipped** (a mutation, a signal/status probe, or ambiguous).

Read-only safety is the hard, non-negotiable rule: a tool whose name implies a
*mutation* (``send`` / ``delete`` / ``write`` / ``create`` …) is classified
``SKIP`` **first**, before any allow decision, so the engine can never call it.
The MCP ``annotations`` (``readOnlyHint`` / ``destructiveHint``) are honored
when present; absent them we fall back to a conservative verb allow/deny list.

This module is pure (no I/O) so it is exhaustively unit-testable.
"""

from __future__ import annotations

import re
from enum import Enum


class ToolRole(str, Enum):
    ENUMERATE = "enumerate"
    FETCH = "fetch"
    SKIP = "skip"


# A tool whose name contains any of these tokens is a MUTATION and is never
# eligible to be called — checked first, never overridable by a recipe/allow-list.
MUTATION_TOKENS: frozenset[str] = frozenset(
    {
        "create", "update", "delete", "remove", "send", "reply", "write",
        "patch", "move", "add", "set", "edit", "insert", "upload", "copy",
        "trigger", "respond", "label", "unlabel", "archive", "mark", "post",
        "put", "merge", "revoke", "rename", "share", "invite", "approve",
        "complete", "cancel", "schedule", "draft", "react", "pin", "unpin",
        "clear", "star", "unstar", "follow", "unfollow", "subscribe", "join",
        "leave", "accept", "decline", "assign", "close", "reopen", "publish",
        "batch", "bulk", "import", "deauthorize", "authenticate",
    }
)

# Read verbs that make a tool eligible (it has to be one of these unless the
# server explicitly annotates the tool read-only).
READ_TOKENS: frozenset[str] = frozenset(
    {
        "list", "search", "get", "read", "fetch", "query", "recent", "history",
        "export", "download", "browse", "find", "lookup", "show", "view",
        "messages", "message", "digest", "feed", "all", "today", "thread",
        "threads", "chats", "events", "files", "notes", "drafts", "labels",
    }
)

# Among read-only survivors, these tokens lean ENUMERATE (return many rows).
ENUMERATE_TOKENS: frozenset[str] = frozenset(
    {
        "list", "search", "recent", "browse", "query", "find", "history",
        "messages", "digest", "feed", "all", "today", "drafts", "labels",
        "chats", "threads", "events", "files", "notes",
    }
)

# These tokens lean FETCH (return one record by id).
FETCH_TOKENS: frozenset[str] = frozenset(
    {"get", "read", "fetch", "download", "open"}
)

# Status/identity probes — not bulk data; skipped unless paired with an
# enumerate token (e.g. ``get_daily_digest`` is data, ``get_sync_status`` isn't).
SIGNAL_TOKENS: frozenset[str] = frozenset(
    {"status", "me", "whoami", "balance", "ping", "health", "options", "info"}
)

# Request-param names (normalised: lowercased, underscores stripped) that mean
# "this tool paginates" — strong ENUMERATE signal.
PAGINATION_PARAMS: frozenset[str] = frozenset(
    {
        "pagetoken", "cursor", "nextcursor", "before", "after", "offset",
        "page", "startcursor", "lastpulledat", "pagecursor", "fromid", "minid",
        "maxid", "continuationtoken", "skip",
    }
)

_CAMEL_BOUND = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokens(name: str) -> list[str]:
    """Split a tool/param name into lowercased tokens (snake_case + camelCase)."""
    spaced = _CAMEL_BOUND.sub(" ", name).replace("_", " ").replace("-", " ")
    return [t.lower() for t in spaced.split() if t]


def _norm_param(name: str) -> str:
    return name.replace("_", "").replace("-", "").lower()


def looks_like_id_param(name: str) -> bool:
    """A param that identifies a single record (``thread_id`` / ``uri`` / ``path``)."""
    n = _norm_param(name)
    if n in {"id", "uri", "url", "path", "key", "ref", "slug", "guid", "uuid"}:
        return True
    return n.endswith("id") or n.endswith("ids") or n.endswith("uri") or n.endswith("path")


def _properties(schema: dict | None) -> dict:
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _required(schema: dict | None) -> list[str]:
    if not isinstance(schema, dict):
        return []
    req = schema.get("required")
    return list(req) if isinstance(req, list) else []


def has_pagination(schema: dict | None) -> bool:
    return any(_norm_param(p) in PAGINATION_PARAMS for p in _properties(schema))


def pagination_param(schema: dict | None) -> str | None:
    """The actual request param name used for paging, if any."""
    for p in _properties(schema):
        if _norm_param(p) in PAGINATION_PARAMS:
            return p
    return None


def required_id_params(schema: dict | None) -> list[str]:
    return [p for p in _required(schema) if looks_like_id_param(p)]


def is_mutation(name: str, annotations: dict | None = None) -> bool:
    """True if the tool mutates state (must never be called). Annotations win."""
    ann = annotations or {}
    if ann.get("destructiveHint") is True:
        return True
    if ann.get("readOnlyHint") is False:
        return True
    return any(t in MUTATION_TOKENS for t in tokens(name))


def classify_tool(
    name: str,
    input_schema: dict | None = None,
    annotations: dict | None = None,
) -> ToolRole:
    """Classify one tool as ENUMERATE / FETCH / SKIP.

    Order matters: the mutation gate runs first (read-only safety), then we
    require a read signal, then disambiguate enumerate vs fetch from the schema.
    """
    # 1. Mutation gate — hard, first, non-overridable.
    if is_mutation(name, annotations):
        return ToolRole.SKIP

    toks = tokens(name)
    tok_set = set(toks)
    read_only_hint = (annotations or {}).get("readOnlyHint")

    # 2. Must look read-only: explicit annotation, or a read verb in the name.
    if read_only_hint is not True and not (tok_set & READ_TOKENS):
        return ToolRole.SKIP

    # 3. Signal/status probes (get_sync_status, me, get_balance) are not bulk
    #    data — skip unless the name also carries an enumerate token.
    if (tok_set & SIGNAL_TOKENS) and not (tok_set & ENUMERATE_TOKENS):
        return ToolRole.SKIP

    has_enum = bool(tok_set & ENUMERATE_TOKENS)
    has_fetch = bool(tok_set & FETCH_TOKENS)
    id_required = required_id_params(input_schema)
    paginated = has_pagination(input_schema)

    # FETCH: a get/read taking a required id and not paginating.
    if has_fetch and id_required and not paginated and not has_enum:
        return ToolRole.FETCH

    # ENUMERATE: explicit list/search token, OR paginates, OR no required id
    #            (so it returns a collection).
    if has_enum or paginated or not id_required:
        return ToolRole.ENUMERATE

    # get_* with a required id but an enumerate-ish token already handled above;
    # a remaining get_* + id is a fetch.
    if has_fetch and id_required:
        return ToolRole.FETCH

    return ToolRole.SKIP


def singularize(noun: str) -> str:
    """Crude singular for noun-matching (threads->thread, files->file)."""
    if noun.endswith("ies") and len(noun) > 3:
        return noun[:-3] + "y"
    if noun.endswith("ses") and len(noun) > 3:
        return noun[:-2]
    if noun.endswith("s") and not noun.endswith("ss") and len(noun) > 1:
        return noun[:-1]
    return noun


# Verbs/qualifiers to drop when extracting the data noun from a tool name.
_NOUN_DROP: frozenset[str] = FETCH_TOKENS | {
    "list", "search", "recent", "query", "find", "browse", "history", "today", "daily", "my",
}


def data_noun(name: str) -> str | None:
    """The collection noun an enumerate/fetch tool operates on.

    ``search_threads`` -> ``thread``; ``list_chats`` -> ``chat``;
    ``get_chat_messages`` -> ``message``; ``read_note`` -> ``note``.
    """
    nouns = [t for t in tokens(name) if t not in _NOUN_DROP]
    if not nouns:
        return None
    return singularize(nouns[-1])
