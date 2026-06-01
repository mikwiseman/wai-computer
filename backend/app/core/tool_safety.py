"""Host-side, fail-closed classification of whether a tool call mutates state.

The HOST decides which tool calls need approval — NEVER a model- or
MCP-server-supplied ``readOnlyHint`` (the MCP spec itself documents tool
annotations as *untrusted hints*: a server can claim ``readOnlyHint: true`` and
still delete your files). Ported from OpenClaw's ``tool-mutation.ts``: a
read-only verb/name allow-list, an explicit mutating-verb set, and name
heuristics. Anything unrecognized is treated as **mutating** (fail closed) so a
new tool can never silently act without an approval.

``build_action_fingerprint`` produces a stable content-address of (tool, args)
that the approval gate stores at propose-time and re-verifies at commit, so an
edited or injected payload cannot be approved as something else.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Verb tokens (the leading segment of a tool name, or an explicit ``action``
# argument) that are unambiguously read-only.
READ_ONLY_ACTIONS: frozenset[str] = frozenset(
    {
        "get", "list", "read", "status", "show", "fetch", "search", "query",
        "view", "poll", "log", "logs", "inspect", "check", "probe", "find",
        "lookup", "describe", "summary", "summarize", "count", "stats",
    }
)

# Verb tokens that unambiguously mutate state and/or leave the device.
MUTATING_ACTIONS: frozenset[str] = frozenset(
    {
        "send", "reply", "post", "create", "update", "edit", "delete",
        "remove", "write", "draft", "schedule", "cancel", "move", "rename",
        "share", "publish", "purchase", "pay", "charge", "react", "pin",
        "unpin", "forward", "insert", "open", "click", "type", "press",
        "set", "run", "execute", "approve", "invite", "add", "drag", "scroll",
        "hotkey", "upload", "download",
    }
)

# Exact first-party tool names whose verb does not classify cleanly. These win
# over the verb heuristics below.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        # companion internal read tools
        "search_transcripts", "get_recording_summary", "list_recordings",
        "get_action_items", "get_highlights", "search_people",
        # WaiComputer MCP read tools
        "fetch", "list_folders", "list_action_items",
        # hosted web search: ingests *untrusted* content (taint!) but does not
        # itself act externally — read-classified, the trifecta gate handles taint.
        "web_search",
        # the router meta-tool that asks for more tools is itself read-only
        "request_tool_group",
    }
)

MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        # writes durable long-term memory — a state change, gate-eligible
        "remember",
        # first-party Telegram send hands
        "send_message_telegram", "reply_to_message_telegram", "send_file_telegram",
    }
)

# Namespaces whose every call mutates / touches the OS regardless of verb.
_MUTATING_NAME_PREFIXES: tuple[str, ...] = ("desktop", "actuate", "actuate_")


def is_mutating_tool_call(name: str, args: dict[str, Any] | None = None) -> bool:
    """Return True when this tool call must pass the approval gate.

    Fail-closed: an unrecognized tool is treated as mutating.
    """
    n = (name or "").strip()
    if not n:
        return True  # nameless call → fail closed
    if n in READ_ONLY_TOOLS:
        return False
    if n in MUTATING_TOOLS:
        return True

    args = args or {}
    action = str(args.get("action", "")).strip().lower()
    if action in MUTATING_ACTIONS:
        return True
    if action in READ_ONLY_ACTIONS:
        return False

    lowered = n.lower()
    if any(lowered.startswith(p) for p in _MUTATING_NAME_PREFIXES) or "_actions" in lowered:
        return True

    # Leading verb segment, tolerating a ``namespace.verb_object`` shape.
    head = lowered.split(".")[-1]
    first = head.split("_")[0]
    if first in READ_ONLY_ACTIONS:
        return False
    if first in MUTATING_ACTIONS:
        return True

    # Last resort substring scan for clearly side-effecting verbs.
    if any(tok in lowered for tok in ("send", "write", "delete", "charge", "pay")):
        return True

    # Unknown shape → fail closed (require approval).
    return True


def _canonical(value: Any) -> Any:
    """Recursively normalize a value for stable hashing (dict key order is
    handled by ``json.dumps(sort_keys=True)``; this drops ``None`` ambiguity)."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def build_action_fingerprint(tool: str, args: dict[str, Any] | None) -> str:
    """A stable sha256 over (tool, normalized args), independent of key order.

    Stored at propose-time and re-verified at commit so the committed action is
    byte-for-byte the approved one (OpenClaw stored-plan immutability)."""
    canonical = json.dumps(
        {"tool": tool, "args": _canonical(args or {})},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
