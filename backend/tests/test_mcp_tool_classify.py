"""Unit tests for the deterministic MCP tool classifier (no I/O)."""

from app.core.mcp_tool_classify import (
    ToolRole,
    classify_tool,
    data_noun,
    is_mutation,
    looks_like_id_param,
    singularize,
)


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


# ── mutation gate (read-only safety) ────────────────────────────────────────
def test_mutating_tools_are_skipped():
    for name in [
        "send_message", "reply_to_message", "delete_event", "create_draft",
        "create_event", "update_event", "write_note", "patch_note", "move_file",
        "label_thread", "unlabel_message", "remove_from_library", "send_file",
        "transactions_create", "transactions_bulk_update", "create_playlist",
        "respond_to_event", "react", "edit_message",
    ]:
        assert classify_tool(name) is ToolRole.SKIP, name


def test_destructive_annotation_forces_skip_even_with_read_name():
    # A deceptively-named "get" tool that the server marks destructive.
    assert classify_tool("get_and_purge", annotations={"destructiveHint": True}) is ToolRole.SKIP
    assert classify_tool("list_things", annotations={"readOnlyHint": False}) is ToolRole.SKIP


def test_is_mutation_token_based_not_substring():
    # "reset" contains "set" but is one token -> not a mutation by substring.
    assert is_mutation("reset_password") is False  # tokens [reset, password]
    assert is_mutation("settings_get") is False    # "settings" != "set"
    assert is_mutation("set_status") is True        # token "set"


# ── enumerate vs fetch ──────────────────────────────────────────────────────
def test_enumerate_tools():
    cases = [
        ("list_chats", _schema({"limit": {}})),
        ("search_threads", _schema({"query": {}, "pageToken": {}, "pageSize": {}})),
        ("search_messages", _schema({"query": {}})),
        ("search_files", _schema({"query": {}, "pageToken": {}})),
        ("list_events", _schema({"calendarId": {}, "pageToken": {}})),
        ("list_recent_files", _schema({})),
        ("time_entries_list", _schema({"cursor": {}, "limit": {}})),
        ("get_daily_digest", _schema({})),
    ]
    for name, schema in cases:
        assert classify_tool(name, schema) is ToolRole.ENUMERATE, name


def test_fetch_tools():
    cases = [
        ("get_thread", _schema({"threadId": {}}, ["threadId"])),
        ("read_note", _schema({"path": {}}, ["path"])),
        ("read_file_content", _schema({"fileId": {}}, ["fileId"])),
        ("get_event", _schema({"eventId": {}}, ["eventId"])),
    ]
    for name, schema in cases:
        assert classify_tool(name, schema) is ToolRole.FETCH, name


def test_scoped_enumerate_with_pagination_is_enumerate_not_fetch():
    # get_chat_messages requires chat_id (id-ish) but paginates -> ENUMERATE
    # (a recipe injects the chat_id scope).
    schema = _schema({"chat_id": {}, "before": {}, "limit": {}}, ["chat_id"])
    assert classify_tool("get_chat_messages", schema) is ToolRole.ENUMERATE


# ── signal/status probes are not bulk data ─────────────────────────────────
def test_signal_probes_skipped():
    for name in ["me", "get_balance", "get_sync_status", "get_data_status", "whoami"]:
        assert classify_tool(name, _schema({})) is ToolRole.SKIP, name


# ── helpers ─────────────────────────────────────────────────────────────────
def test_looks_like_id_param():
    assert looks_like_id_param("threadId")
    assert looks_like_id_param("chat_id")
    assert looks_like_id_param("path")
    assert looks_like_id_param("uri")
    assert not looks_like_id_param("query")
    assert not looks_like_id_param("limit")


def test_singularize():
    assert singularize("threads") == "thread"
    assert singularize("files") == "file"
    assert singularize("entries") == "entry"
    assert singularize("messages") == "message"
    assert singularize("note") == "note"


def test_data_noun():
    assert data_noun("search_threads") == "thread"
    assert data_noun("list_chats") == "chat"
    assert data_noun("get_chat_messages") == "message"
    assert data_noun("read_note") == "note"
    assert data_noun("search_files") == "file"
