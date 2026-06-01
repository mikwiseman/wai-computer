"""Host-side mutation classifier + action fingerprint (P2)."""

from app.core.tool_safety import (
    build_action_fingerprint,
    is_mutating_tool_call,
)


def test_known_read_tools_are_not_mutating():
    for name in [
        "search_transcripts", "get_recording_summary", "list_recordings",
        "get_action_items", "get_highlights", "search_people",
        "fetch", "list_folders", "list_action_items", "web_search",
        "request_tool_group",
    ]:
        assert is_mutating_tool_call(name) is False, name


def test_known_write_tools_are_mutating():
    for name in ["remember", "send_message_telegram", "reply_to_message_telegram"]:
        assert is_mutating_tool_call(name) is True, name


def test_verb_prefix_classifies_reads_and_writes():
    assert is_mutating_tool_call("list_widgets") is False
    assert is_mutating_tool_call("get_thing") is False
    assert is_mutating_tool_call("search_web") is False
    assert is_mutating_tool_call("send_widget") is True
    assert is_mutating_tool_call("create_event") is True
    assert is_mutating_tool_call("delete_note") is True


def test_action_argument_overrides_when_present():
    # A generic tool name disambiguated by an explicit action arg.
    assert is_mutating_tool_call("messages", {"action": "send"}) is True
    assert is_mutating_tool_call("messages", {"action": "list"}) is False
    assert is_mutating_tool_call("calendar", {"action": "create"}) is True
    assert is_mutating_tool_call("calendar", {"action": "view"}) is False


def test_desktop_and_actuate_namespace_always_mutating():
    assert is_mutating_tool_call("desktop_click", {"index": 3}) is True
    assert is_mutating_tool_call("actuate_open", {"app": "Mail"}) is True
    assert is_mutating_tool_call("message_actions", {"action": "anything"}) is True


def test_unknown_and_nameless_fail_closed():
    # Anything we don't recognize is treated as mutating (requires approval).
    assert is_mutating_tool_call("frobnicate_quux") is True
    assert is_mutating_tool_call("") is True
    assert is_mutating_tool_call(None) is True  # type: ignore[arg-type]


def test_fingerprint_is_stable_across_key_order():
    a = build_action_fingerprint("send", {"to": "anna", "text": "hi"})
    b = build_action_fingerprint("send", {"text": "hi", "to": "anna"})
    assert a == b


def test_fingerprint_changes_on_payload_or_tool_change():
    base = build_action_fingerprint("send", {"to": "anna", "text": "hi"})
    assert base != build_action_fingerprint("send", {"to": "anna", "text": "bye"})
    assert base != build_action_fingerprint("send", {"to": "bob", "text": "hi"})
    assert base != build_action_fingerprint("post", {"to": "anna", "text": "hi"})


def test_fingerprint_handles_nested_and_is_hex_sha256():
    fp = build_action_fingerprint("x", {"a": {"b": [1, 2, {"c": 3}]}})
    assert len(fp) == 64
    assert all(ch in "0123456789abcdef" for ch in fp)
