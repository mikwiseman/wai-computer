"""Unit tests for ingestion plan resolution (heuristic + recipe match)."""

from app.core.mcp_plan import (
    McpToolDescriptor,
    infer_kind,
    plan_tools,
    resolve_plan_from_tools,
)
from app.core.mcp_recipes import match_recipe


def _t(name, props=None, required=None, annotations=None) -> McpToolDescriptor:
    return McpToolDescriptor(
        name=name,
        input_schema={"type": "object", "properties": props or {}, "required": required or []},
        annotations=annotations,
    )


def test_heuristic_builds_enumerate_fetch_step():
    tools = [
        _t("search_threads", {"query": {}, "pageToken": {}, "pageSize": {}}),
        _t("get_thread", {"threadId": {}}, ["threadId"]),
        _t("send_message", {"to": {}}),  # mutation -> ignored
    ]
    plan = resolve_plan_from_tools(tools)
    assert plan is not None
    assert plan.planned_by == "heuristic"
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.enumerate_tool == "search_threads"
    assert step.fetch_tool == "get_thread"
    assert step.fetch_arg == "threadId"
    assert step.kind == "email"
    assert step.cursor is not None
    assert step.cursor.page_param == "pageToken"
    # The mutation tool is never in the allow-list.
    assert "send_message" not in plan_tools(plan)
    assert plan_tools(plan) == {"search_threads", "get_thread"}


def test_heuristic_skips_scoped_enumerate_needing_id():
    # get_chat_messages needs chat_id -> heuristic can't self-serve it; with no
    # other enumerate tool the plan is unresolvable (-> needs_setup).
    tools = [_t("get_chat_messages", {"chat_id": {}, "before": {}}, ["chat_id"])]
    assert resolve_plan_from_tools(tools) is None


def test_heuristic_none_when_no_enumerate():
    tools = [_t("get_thread", {"threadId": {}}, ["threadId"]), _t("me", {})]
    assert resolve_plan_from_tools(tools) is None


def test_infer_kind():
    assert infer_kind("search_threads", "get_thread") == "email"
    assert infer_kind("list_chats", "get_chat_messages") == "message"
    assert infer_kind("list_events") == "event"
    assert infer_kind("search_files", "read_file_content") == "file"
    assert infer_kind("search_notes", "read_note") == "note"
    assert infer_kind("list_widgets") == "mcp_item"


def test_recipe_match_telegram_beats_heuristic():
    plan = match_recipe({"list_chats", "get_chat_messages", "search_messages", "send_message"})
    assert plan is not None
    assert plan.planned_by == "recipe"
    step = plan.steps[0]
    assert step.enumerate_tool == "get_chat_messages"
    assert step.scope_tool == "list_chats"
    assert step.scope_arg == "chat_id"
    assert step.kind == "message"
    assert "send_message" not in plan_tools(plan)


def test_recipe_match_none_for_unknown_server():
    assert match_recipe({"frobnicate", "wibble"}) is None
