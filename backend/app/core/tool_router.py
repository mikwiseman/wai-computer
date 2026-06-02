"""Tool routing: organize every tool into a GROUP and expose only a small
per-turn PROFILE so the model never faces a flat 40-tool list.

Re-implements the Anthropic Tool-Search / RAG-MCP "defer loading" pattern for
the OpenAI Responses API (where the literal ``defer_loading`` param is
unavailable): a small default set plus a ``request_tool_group()`` meta-tool the
model calls to pull in a group on demand; the iterating loop re-attaches that
group's tools on the next step. Empirically this keeps per-turn tool count low
(~10-14) where selection stays accurate.

Dangerous write / OS groups have EMPTY default-profile membership (opt-in). A
``DENY_ALWAYS`` set is unreachable by any turn regardless of profile/request.
Ordered resolution: profile defaults ∪ requested − denied − DENY_ALWAYS.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# group -> ordered tool names (the function-tool surface the host dispatches and
# gates; the read-only WaiComputer MCP tool is attached separately and is not a
# member here). Write/OS groups are filled in as their phases land.
TOOL_GROUPS: dict[str, list[str]] = {
    "read": [
        "search_transcripts", "get_recording_summary", "list_recordings",
        "get_action_items", "get_highlights", "search_people",
    ],
    "memory": ["remember"],
    "web": ["web_search"],
    "telegram": [
        "send_message_telegram",
        "reply_to_message_telegram",
        "send_file_telegram",
    ],
    "gmail": [],      # connector writes — populated in P5
    "calendar": [],   # connector writes — populated in P5
    "drive": [],      # connector reads/writes — populated in P5
    "desktop": ["desktop_open", "desktop_type", "desktop_click"],
}

# profile -> groups exposed by default at the start of a turn. Write/OS groups
# are intentionally absent (opt-in via request_tool_group).
PROFILES: dict[str, frozenset[str]] = {
    "voice_default": frozenset({"read", "memory", "web"}),
    "chat_default": frozenset({"read", "memory", "web"}),
}

# Tools no turn may ever reach regardless of profile/request (e.g. irreversible
# financial charges). Populated as such tools are introduced.
DENY_ALWAYS: frozenset[str] = frozenset()

REQUEST_TOOL_GROUP_NAME = "request_tool_group"


def all_groups() -> list[str]:
    return list(TOOL_GROUPS.keys())


def group_of(tool_name: str) -> str | None:
    for group, names in TOOL_GROUPS.items():
        if tool_name in names:
            return group
    return None


def default_groups(profile: str = "voice_default") -> frozenset[str]:
    return PROFILES.get(profile, PROFILES["voice_default"])


def resolve_active_groups(
    profile: str = "voice_default",
    requested: Iterable[str] = (),
    denied: Iterable[str] = (),
) -> set[str]:
    """profile defaults ∪ (requested groups that exist) − denied."""
    active = set(default_groups(profile))
    for g in requested:
        if g in TOOL_GROUPS:
            active.add(g)
    active.difference_update(set(denied))
    return active


def visible_tool_names(active_groups: Iterable[str]) -> list[str]:
    """Ordered, de-duplicated tool names visible for the given active groups,
    minus the DENY_ALWAYS set."""
    names: list[str] = []
    for group in active_groups:
        for name in TOOL_GROUPS.get(group, []):
            if name not in DENY_ALWAYS and name not in names:
                names.append(name)
    return names


def requestable_groups(profile: str = "voice_default") -> list[str]:
    """Non-default groups that currently have ≥1 tool — the only groups worth
    offering the model to request."""
    default = default_groups(profile)
    return sorted(
        g for g, names in TOOL_GROUPS.items() if g not in default and names
    )


def request_tool_group_tool(profile: str = "voice_default") -> dict[str, Any]:
    """The meta-tool the model calls to pull in an opt-in group on demand."""
    return {
        "type": "function",
        "name": REQUEST_TOOL_GROUP_NAME,
        "description": (
            "Request access to a group of tools you don't currently have, when "
            "the user's request needs it (e.g. 'telegram' to message someone). "
            "Only ask for the one group you need."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "enum": requestable_groups(profile)},
            },
            "required": ["group"],
            "additionalProperties": False,
        },
    }


def filter_tool_defs(
    tool_defs: list[dict[str, Any]], active_groups: Iterable[str]
) -> list[dict[str, Any]]:
    """Keep only the tool definitions whose name is visible for active_groups."""
    visible = set(visible_tool_names(active_groups))
    return [t for t in tool_defs if t.get("name") in visible]
