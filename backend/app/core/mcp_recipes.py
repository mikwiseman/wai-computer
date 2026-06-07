"""Hand-tuned ingestion recipes for known MCP servers.

The heuristic planner (:mod:`app.core.mcp_plan`) handles the long tail of
unknown servers, but the big known ones have cross-noun shapes a generic
classifier can't infer — Telegram enumerates *chats* but you fetch *messages*
via ``get_chat_messages(chat_id)``; Notion's ``search`` returns results you then
fetch by id. A recipe pins those.

A recipe is pure data: a set of required tool names (matched as a subset of the
server's advertised tools — **not** by URL, which varies per user) and a
:class:`IngestionPlan`. Adding a connector is appending one entry here; the
executor never changes. Recipes are still subject to the mutation gate at call
time, so a recipe can never cause a write.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.mcp_plan import CursorSpec, FetchStep, FieldMap, IngestionPlan


@dataclass(frozen=True)
class Recipe:
    name: str
    requires: frozenset[str]            # all must be advertised by the server
    build: Callable[[], IngestionPlan]


def _telegram() -> IngestionPlan:
    # Enumerate chats, then page each chat's messages (scope = chat_id).
    return IngestionPlan(
        strategy="tools",
        planned_by="recipe",
        tools_used=["list_chats", "get_chat_messages"],
        steps=[
            FetchStep(
                enumerate_tool="get_chat_messages",
                enumerate_args={"limit": 100},
                scope_tool="list_chats",
                scope_id_path="chat_id",
                scope_arg="chat_id",
                record_path="messages",
                cursor=CursorSpec(page_param="before", page_size_param="limit", page_size=100),
                kind="message",
                field_map=FieldMap(
                    title=["text", "message", "caption"],
                    body=["text", "message", "caption"],
                    occurred_at=["date", "timestamp"],
                    source_ref=["message_id", "id"],
                    url=[],
                ),
            )
        ],
    )


def _notion() -> IngestionPlan:
    return IngestionPlan(
        strategy="tools",
        planned_by="recipe",
        tools_used=["search", "fetch"],
        steps=[
            FetchStep(
                enumerate_tool="search",
                enumerate_args={"query": ""},
                record_path="results",
                fetch_tool="fetch",
                fetch_arg="id",
                cursor=CursorSpec(page_param="start_cursor", next_path="next_cursor"),
                kind="note",
                field_map=FieldMap(
                    title=["title", "name", "properties.title"],
                    body=["content", "plain_text", "text", "markdown"],
                    occurred_at=["last_edited_time", "created_time"],
                    source_ref=["id", "url"],
                    url=["url"],
                ),
            )
        ],
    )


def _gmail() -> IngestionPlan:
    return IngestionPlan(
        strategy="tools",
        planned_by="recipe",
        tools_used=["search_threads", "get_thread"],
        steps=[
            FetchStep(
                enumerate_tool="search_threads",
                enumerate_args={"query": "newer_than:90d"},
                record_path="threads",
                id_path="id",
                fetch_tool="get_thread",
                fetch_arg="threadId",
                fetch_record_path="messages",
                cursor=CursorSpec(
                    page_param="pageToken", next_path="nextPageToken",
                    page_size_param="pageSize", page_size=50,
                ),
                kind="email",
                field_map=FieldMap(
                    title=["subject", "snippet"],
                    body=["plaintext_body", "body", "text", "snippet"],
                    occurred_at=["date", "internalDate"],
                    source_ref=["id", "messageId"],
                    url=[],
                ),
            )
        ],
    )


def _obsidian() -> IngestionPlan:
    return IngestionPlan(
        strategy="tools",
        planned_by="recipe",
        tools_used=["search_notes", "read_note"],
        steps=[
            FetchStep(
                enumerate_tool="search_notes",
                enumerate_args={"query": ""},
                record_path="results",
                id_path="path",
                fetch_tool="read_note",
                fetch_arg="path",
                kind="note",
                field_map=FieldMap(
                    title=["basename", "title", "path"],
                    body=["content", "text"],
                    occurred_at=["mtime", "modified", "modified_at"],
                    source_ref=["path"],
                    url=[],
                ),
            )
        ],
    )


def _wai_time() -> IngestionPlan:
    return IngestionPlan(
        strategy="tools",
        planned_by="recipe",
        tools_used=["time_entries_list"],
        steps=[
            FetchStep(
                enumerate_tool="time_entries_list",
                record_path="time_entries",
                cursor=CursorSpec(
                    page_param="cursor", next_path="next_cursor",
                    page_size_param="limit", page_size=100,
                ),
                kind="event",
                field_map=FieldMap(
                    title=["description", "project_name", "name"],
                    body=["description", "note", "notes"],
                    occurred_at=["start", "start_time", "started_at", "date"],
                    source_ref=["id"],
                    url=[],
                ),
            )
        ],
    )


def _wai_money() -> IngestionPlan:
    return IngestionPlan(
        strategy="tools",
        planned_by="recipe",
        tools_used=["transactions_list"],
        steps=[
            FetchStep(
                enumerate_tool="transactions_list",
                record_path="transactions",
                cursor=CursorSpec(
                    page_param="cursor", next_path="next_cursor",
                    page_size_param="limit", page_size=100,
                ),
                kind="transaction",
                field_map=FieldMap(
                    title=["description", "merchant", "payee", "note"],
                    body=["description", "note", "notes", "memo"],
                    occurred_at=["date", "posted_at", "occurred_at"],
                    source_ref=["id"],
                    url=[],
                ),
            )
        ],
    )


RECIPES: list[Recipe] = [
    Recipe("telegram", frozenset({"list_chats", "get_chat_messages"}), _telegram),
    Recipe("gmail", frozenset({"search_threads", "get_thread"}), _gmail),
    Recipe("notion", frozenset({"search", "fetch"}), _notion),
    Recipe("obsidian", frozenset({"search_notes", "read_note"}), _obsidian),
    Recipe("wai_time", frozenset({"time_entries_list"}), _wai_time),
    Recipe("wai_money", frozenset({"transactions_list"}), _wai_money),
]


def match_recipe(tool_names: set[str] | list[str]) -> IngestionPlan | None:
    """Return the first recipe whose required tools the server advertises."""
    available = set(tool_names)
    for recipe in RECIPES:
        if recipe.requires <= available:
            return recipe.build()
    return None
