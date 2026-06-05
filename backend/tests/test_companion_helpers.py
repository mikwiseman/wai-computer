"""Unit tests for pure helpers in app.core.companion (prompt assembly,
event dataclasses, scope formatting). The turn-loop is covered separately
by test_companion_loop.py — this file targets the smaller helpers that
were not exercised."""

from __future__ import annotations

import json
import uuid

import pytest

from app.core.companion import (
    SYSTEM_PROMPT,
    CitationEvent,
    CompanionError,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnContext,
    TurnStartEvent,
    _build_session_developer_message,
    _extract_mcp_context_items,
    _extract_text,
    _extract_tool_calls,
    _format_scope_for_session,
    _format_weekday,
    _get_usage,
    _history_to_responses_input,
    _intersect_recording_ids,
    _render_memory_section,
    _render_user_profile,
    _response_item_to_dict,
    _scope_brain_space_uuid,
    _scope_recording_uuids,
    _summary_one_line,
    final_answer_schema,
    system_prompt_for,
    tool_definitions,
)

# ---------------------------------------------------------------------------
# _render_user_profile
# ---------------------------------------------------------------------------


def test_render_user_profile_returns_empty_when_no_user() -> None:
    assert _render_user_profile(None) == ""


def test_render_user_profile_includes_languages_and_style() -> None:
    class FakeUser:
        default_language = "en"
        summary_language = "ru"
        summary_style = "bullet"
        summary_instructions = None

    rendered = _render_user_profile(FakeUser())
    assert "<user_profile>" in rendered
    assert "default_language: en" in rendered
    assert "summary_language: ru" in rendered
    assert "summary_style: bullet" in rendered
    assert "summary_instructions" not in rendered
    assert "</user_profile>" in rendered


def test_render_user_profile_truncates_summary_instructions_to_240_chars() -> None:
    class FakeUser:
        default_language = "en"
        summary_language = "en"
        summary_style = "bullet"
        summary_instructions = "x" * 300

    rendered = _render_user_profile(FakeUser())
    line = next(
        line
        for line in rendered.split("\n")
        if line.startswith("summary_instructions:")
    )
    # "summary_instructions: " (22 chars) + up to 240 of body = 262 chars
    assert len(line) <= 22 + 240


def test_render_user_profile_strips_summary_instructions_before_truncation() -> None:
    class FakeUser:
        default_language = "en"
        summary_language = "en"
        summary_style = "bullet"
        summary_instructions = "   hello world   "

    rendered = _render_user_profile(FakeUser())
    assert "summary_instructions: hello world" in rendered


# ---------------------------------------------------------------------------
# _render_memory_section
# ---------------------------------------------------------------------------


def test_render_memory_returns_empty_when_none() -> None:
    assert _render_memory_section(None) == ""
    assert _render_memory_section({}) == ""


def test_render_memory_returns_empty_when_all_blocks_empty() -> None:
    assert _render_memory_section({"insights": "", "preferences": "   "}) == ""


def test_render_memory_includes_named_sections() -> None:
    blocks = {"insights": "Mik likes minimalism.", "preferences": "  Prefers concise output.  "}
    rendered = _render_memory_section(blocks)
    assert rendered.startswith("<memory>")
    assert rendered.endswith("</memory>")
    assert "## insights" in rendered
    assert "Mik likes minimalism." in rendered
    assert "## preferences" in rendered
    assert "Prefers concise output." in rendered


# ---------------------------------------------------------------------------
# system_prompt_for
# ---------------------------------------------------------------------------


def test_system_prompt_for_no_user_returns_static_sections() -> None:
    prompt = system_prompt_for()
    assert "<identity>" in prompt
    assert "<user_profile>" not in prompt
    # No <memory> SECTION; the word may still appear inside <tool_guidance>.
    assert "<memory>\n##" not in prompt


def test_system_prompt_for_with_user_appends_profile() -> None:
    class FakeUser:
        default_language = "en"
        summary_language = "en"
        summary_style = "bullet"
        summary_instructions = None

    prompt = system_prompt_for(user=FakeUser())
    # Identity section appears before user_profile
    identity_idx = prompt.index("<identity>")
    profile_idx = prompt.index("<user_profile>")
    assert identity_idx < profile_idx


def test_system_prompt_for_with_memory_appends_memory_section() -> None:
    prompt = system_prompt_for(memory_blocks={"insights": "test"})
    assert "<memory>" in prompt
    assert "## insights" in prompt


def test_system_prompt_constant_equals_no_args_call() -> None:
    assert SYSTEM_PROMPT == system_prompt_for()


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


def test_turn_start_event_defaults() -> None:
    e = TurnStartEvent(message_id="m1", conversation_id="c1")
    assert e.type == "turn_start"
    assert e.message_id == "m1"
    assert e.conversation_id == "c1"


def test_tool_call_event_with_args() -> None:
    e = ToolCallEvent(call_id="tc1", tool="search", args={"query": "x"})
    assert e.type == "tool_call"
    assert e.args == {"query": "x"}


def test_tool_result_event_defaults() -> None:
    e = ToolResultEvent(call_id="tc1", summary="found 3 results")
    assert e.summary == "found 3 results"


def test_token_event_defaults() -> None:
    e = TokenEvent(text="hello")
    assert e.text == "hello"


def test_citation_event_optional_timestamps() -> None:
    e = CitationEvent(index=1, segment_id="s1", recording_id="r1", span_start=0, span_end=5)
    assert e.start_ms is None
    assert e.end_ms is None
    assert e.span_start == 0


def test_done_event_with_token_counts() -> None:
    e = DoneEvent(
        message_id="m1", input_tokens=100, output_tokens=50,
        cached_tokens=80, model="gpt", latency_ms=250,
    )
    assert e.input_tokens == 100
    assert e.cached_tokens == 80


def test_error_event_carries_code_and_message() -> None:
    e = ErrorEvent(code="rate_limit", message="too many requests")
    assert e.code == "rate_limit"
    assert e.message == "too many requests"


# ---------------------------------------------------------------------------
# CompanionError
# ---------------------------------------------------------------------------


def test_companion_error_carries_code_and_message() -> None:
    err = CompanionError(code="validator_rejected", message="citations don't match")
    assert err.code == "validator_rejected"
    assert err.message == "citations don't match"
    assert str(err) == "citations don't match"


# ---------------------------------------------------------------------------
# tool_definitions / final_answer_schema
# ---------------------------------------------------------------------------


def test_tool_definitions_returns_function_schemas() -> None:
    tools = tool_definitions()
    assert isinstance(tools, list)
    assert len(tools) > 0
    # Each tool must have name + parameters (OpenAI function-calling schema)
    for tool in tools:
        assert tool["type"] == "function"
        # OpenAI function-tool schema places name/parameters at top level since 2025
        assert tool.get("name") or tool.get("function", {}).get("name")


def test_tool_definitions_includes_search_transcripts() -> None:
    tools = tool_definitions()
    names = []
    for t in tools:
        name = t.get("name") or t.get("function", {}).get("name")
        if name:
            names.append(name)
    assert "search_transcripts" in names


def test_final_answer_schema_is_valid_jsonschema() -> None:
    schema = final_answer_schema()
    assert schema["name"] == "wai_answer"
    assert schema["strict"] is True
    inner = schema["schema"]
    assert inner["type"] == "object"
    assert inner["additionalProperties"] is False
    assert "markdown" in inner["properties"]
    assert "citations" in inner["properties"]
    # citations are arrays of {index, segment_id, span_start, span_end}
    cit_item = inner["properties"]["citations"]["items"]
    assert cit_item["type"] == "object"
    assert set(cit_item["required"]) == {"index", "segment_id", "span_start", "span_end"}


# ---------------------------------------------------------------------------
# _scope_recording_uuids / _intersect_recording_ids
# ---------------------------------------------------------------------------


def test_scope_recording_uuids_returns_none_when_no_scope() -> None:
    assert _scope_recording_uuids(None) is None
    assert _scope_recording_uuids({}) is None
    assert _scope_recording_uuids({"recording_ids": []}) is None


def test_scope_recording_uuids_parses_strings() -> None:
    uid1, uid2 = uuid.uuid4(), uuid.uuid4()
    out = _scope_recording_uuids({"recording_ids": [str(uid1), str(uid2)]})
    assert out is not None
    assert set(out) == {uid1, uid2}


def test_scope_recording_uuids_raises_on_invalid_strings() -> None:
    """Invalid UUID strings in scope raise CompanionError — strict contract,
    no silent skip."""
    with pytest.raises(CompanionError) as exc:
        _scope_recording_uuids({"recording_ids": ["not-a-uuid"]})
    assert exc.value.code == "invalid_scope"


def test_intersect_recording_ids_no_scope_returns_explicit() -> None:
    explicit = [uuid.uuid4(), uuid.uuid4()]
    out = _intersect_recording_ids(explicit=explicit, scope=None)
    assert out == explicit


def test_intersect_recording_ids_only_scope() -> None:
    scope = [uuid.uuid4(), uuid.uuid4()]
    out = _intersect_recording_ids(explicit=None, scope=scope)
    assert out == scope


def test_intersect_recording_ids_intersection() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    out = _intersect_recording_ids(explicit=[b, c], scope=[a, b])
    # explicit ids filtered to only those in scope
    assert out == [b]


# ---------------------------------------------------------------------------
# _summary_one_line
# ---------------------------------------------------------------------------


def test_summary_one_line_none() -> None:
    assert _summary_one_line(None) is None


def test_summary_one_line_takes_first_sentence() -> None:
    class FakeSummary:
        summary = "First sentence. Second sentence with more."

    out = _summary_one_line(FakeSummary())
    assert out is not None
    # Function returns up to 240 chars; should still contain the first sentence.
    assert "First sentence" in out


# ---------------------------------------------------------------------------
# _format_weekday
# ---------------------------------------------------------------------------


def test_format_weekday_valid_iso_date() -> None:
    # 2026-05-18 is a Monday
    assert _format_weekday("2026-05-18") == ", Monday"


def test_format_weekday_unparseable_returns_empty() -> None:
    assert _format_weekday("not-a-date") == ""
    assert _format_weekday("") == ""


def test_format_weekday_handles_invalid_type() -> None:
    # The function catches TypeError as well as ValueError
    assert _format_weekday(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _format_scope_for_session
# ---------------------------------------------------------------------------


def test_format_scope_empty_returns_all_recordings() -> None:
    assert _format_scope_for_session(None) == "all of the user's recordings"
    assert _format_scope_for_session({}) == "all of the user's recordings"


def test_format_scope_with_recording_ids() -> None:
    out = _format_scope_for_session({"recording_ids": ["a", "b", "c"]})
    assert out == "3 pinned recordings"


def test_format_scope_singular_recording() -> None:
    out = _format_scope_for_session({"recording_ids": ["a"]})
    assert out == "1 pinned recording"


def test_format_scope_no_recording_ids_field() -> None:
    out = _format_scope_for_session({"other": "x"})
    assert out == "all of the user's recordings"


def test_format_scope_with_brain_and_recordings() -> None:
    out = _format_scope_for_session(
        {"brain_space_id": str(uuid.uuid4()), "recording_ids": ["a", "b"]}
    )
    assert out == "selected Brain + 2 pinned recordings"


def test_scope_brain_space_uuid_rejects_malformed_id() -> None:
    with pytest.raises(CompanionError) as exc:
        _scope_brain_space_uuid({"brain_space_id": "bad"})
    assert exc.value.code == "invalid_scope"
    assert "brain_space_id" in exc.value.message


# ---------------------------------------------------------------------------
# _build_session_developer_message
# ---------------------------------------------------------------------------


def test_build_session_developer_message_none_when_empty() -> None:
    assert _build_session_developer_message(None, None) is None
    assert _build_session_developer_message(None, {}) is None


def test_build_session_developer_message_with_scope_only() -> None:
    out = _build_session_developer_message(None, {"recording_ids": ["a"]})
    assert out is not None
    assert out["role"] == "developer"
    assert "scope: 1 pinned recording" in out["content"]


def test_build_session_developer_message_with_brain_context() -> None:
    out = _build_session_developer_message(
        None,
        {"brain_space_id": str(uuid.uuid4())},
        brain_context={
            "space": type("Space", (), {"name": "Ops Brain"})(),
            "claim_count": 1,
            "markdown": "# Ops context\n\n## Facts\n- Use 40 minute sessions.",
        },
    )
    assert out is not None
    assert "scope: selected Brain" in out["content"]
    assert "brain: Ops Brain; approved items: 1" in out["content"]
    assert "<brain_context>" in out["content"]
    assert "Use 40 minute sessions." in out["content"]


def test_build_session_developer_message_with_ctx_full() -> None:
    ctx = TurnContext(
        client_local_date="2026-05-18",
        client_timezone="Atlantic/Reykjavik",
        viewing_recording_title="Sprint planning",
        viewing_folder_name="Work",
    )
    out = _build_session_developer_message(ctx, None)
    assert out is not None
    assert "date: 2026-05-18, Monday" in out["content"]
    assert "timezone: Atlantic/Reykjavik" in out["content"]
    assert "viewing recording: Sprint planning" in out["content"]
    assert "viewing folder: Work" in out["content"]


def test_build_session_developer_message_without_date_uses_fallback() -> None:
    ctx = TurnContext(client_local_date=None, client_timezone="UTC")
    out = _build_session_developer_message(ctx, None)
    assert out is not None
    assert "date: unknown" in out["content"]
    assert "timezone: UTC" in out["content"]


def test_build_session_developer_message_without_timezone_uses_fallback() -> None:
    ctx = TurnContext(client_local_date="2026-05-18", client_timezone=None)
    out = _build_session_developer_message(ctx, None)
    assert out is not None
    assert "timezone: unknown" in out["content"]


# ---------------------------------------------------------------------------
# _history_to_responses_input
# ---------------------------------------------------------------------------


def test_history_user_string_content() -> None:
    class M:
        role = "user"
        content = "hello"

    out = _history_to_responses_input([M()])
    assert out == [{"role": "user", "content": "hello"}]


def test_history_assistant_json_content() -> None:
    class M:
        role = "assistant"
        content = {"answer": "hi", "citations": []}

    out = _history_to_responses_input([M()])
    assert out[0]["role"] == "assistant"
    # Non-string content gets JSON-stringified
    parsed = json.loads(out[0]["content"])
    assert parsed == {"answer": "hi", "citations": []}


def test_history_assistant_text_blocks_become_plain_text() -> None:
    class M:
        role = "assistant"
        tool_calls = None
        content = [{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}]

    out = _history_to_responses_input([M()])
    assert out == [{"role": "assistant", "content": "hello world"}]


def test_history_dict_text_content_becomes_plain_text() -> None:
    class M:
        role = "assistant"
        tool_calls = None
        content = {"text": "plain answer"}

    out = _history_to_responses_input([M()])
    assert out == [{"role": "assistant", "content": "plain answer"}]


def test_history_includes_latest_cached_mcp_list_tools() -> None:
    cached = {"type": "mcp_list_tools", "server_label": "wai", "tools": []}

    class Older:
        role = "assistant"
        tool_calls = [{"type": "mcp_list_tools", "server_label": "old", "tools": []}]
        content = "old"

    class Newer:
        role = "assistant"
        tool_calls = [cached]
        content = "new"

    out = _history_to_responses_input([Older(), Newer()])
    assert out[0] == cached


def test_history_skips_tool_role() -> None:
    class U:
        role = "user"
        content = "q"

    class T:
        role = "tool"
        content = "t"

    out = _history_to_responses_input([U(), T()])
    # Only user (and assistant) roles are mapped; tool role dropped
    assert len(out) == 1
    assert out[0]["role"] == "user"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def test_extract_mcp_context_items_from_dict_response() -> None:
    cached = {"type": "mcp_list_tools", "server_label": "wai", "tools": []}
    response = {"output": [{"type": "message"}, cached]}
    assert _extract_mcp_context_items(response) == [cached]


def test_response_item_to_dict_uses_model_dump_when_available() -> None:
    class Item:
        def model_dump(self, *, mode: str, exclude_none: bool) -> dict:
            assert mode == "json"
            assert exclude_none is True
            return {"type": "mcp_list_tools", "server_label": "wai"}

    assert _response_item_to_dict(Item()) == {
        "type": "mcp_list_tools",
        "server_label": "wai",
    }


def test_response_item_to_dict_reads_plain_object_attrs() -> None:
    class Item:
        id = "i1"
        type = "mcp_list_tools"
        server_label = "wai"
        tools = [{"name": "search"}]

    assert _response_item_to_dict(Item()) == {
        "id": "i1",
        "type": "mcp_list_tools",
        "server_label": "wai",
        "tools": [{"name": "search"}],
    }


def test_extract_text_from_output_blocks() -> None:
    response = {
        "output": [
            {"content": [{"type": "output_text", "text": "hello"}]},
            {"content": [{"type": "output_text", "text": " world"}]},
        ]
    }
    assert _extract_text(response) == "hello world"


def test_extract_text_prefers_output_text_field() -> None:
    assert _extract_text({"output_text": "direct"}) == "direct"


def test_extract_tool_calls_from_dict_and_object_items() -> None:
    class Call:
        type = "function_call"
        call_id = "c2"
        name = "fetch"
        arguments = '{"id": "r1"}'

    response = {
        "output": [
            {"type": "message"},
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "search",
                "arguments": '{"query": "x"}',
            },
            Call(),
        ]
    }

    assert _extract_tool_calls(response) == [
        {"id": "c1", "name": "search", "arguments": {"query": "x"}},
        {"id": "c2", "name": "fetch", "arguments": {"id": "r1"}},
    ]


def test_extract_tool_calls_rejects_invalid_json_args() -> None:
    response = {
        "output": [
            {
                "type": "function_call",
                "call_id": "bad",
                "name": "search",
                "arguments": "{",
            }
        ]
    }
    with pytest.raises(CompanionError) as exc:
        _extract_tool_calls(response)
    assert exc.value.code == "invalid_tool_args"


def test_get_usage_reads_cached_tokens_from_details() -> None:
    usage = {
        "input_tokens": 10,
        "output_tokens": 4,
        "input_tokens_details": {"cached_tokens": 7},
    }
    assert _get_usage(usage, "input_tokens") == 10
    assert _get_usage(usage, "output_tokens") == 4
    assert _get_usage(usage, "cached_tokens") == 7


def test_get_usage_reads_cached_tokens_from_object_details() -> None:
    class Details:
        cached_tokens = 3

    class Usage:
        input_tokens = 8
        output_tokens = 5
        input_tokens_details = Details()

    assert _get_usage(Usage(), "input_tokens") == 8
    assert _get_usage(Usage(), "output_tokens") == 5
    assert _get_usage(Usage(), "cached_tokens") == 3
    assert _get_usage(None, "input_tokens") == 0
