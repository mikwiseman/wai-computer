"""Tests for app.core.openai_responses safety helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.openai_responses import (
    OpenAIResponseError,
    ensure_response_completed,
    response_output_text,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _AttrObject:
    """Simple value-object so we can test the getattr branch of `_field`."""

    status: str | None = None
    output_text: str | None = None
    error: Any = None
    output: Any = None
    incomplete_details: Any = None


@dataclass
class _IncompleteDetails:
    reason: str | None = None


# ---------------------------------------------------------------------------
# ensure_response_completed
# ---------------------------------------------------------------------------


def test_completed_dict_passes() -> None:
    ensure_response_completed({"status": "completed", "output": []}, operation="summary")


def test_completed_attr_object_passes() -> None:
    ensure_response_completed(_AttrObject(status="completed", output=[]), operation="summary")


def test_missing_status_treated_as_completed() -> None:
    # The function only raises if status is set and != completed.
    ensure_response_completed({"output": []}, operation="op")


def test_incomplete_without_details_raises() -> None:
    with pytest.raises(OpenAIResponseError, match="did not complete: in_progress"):
        ensure_response_completed({"status": "in_progress"}, operation="op")


def test_incomplete_with_reason_includes_reason_suffix() -> None:
    payload = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    with pytest.raises(
        OpenAIResponseError,
        match=r"did not complete: incomplete \(max_output_tokens\)",
    ):
        ensure_response_completed(payload, operation="op")


def test_incomplete_with_attr_details() -> None:
    obj = _AttrObject(
        status="incomplete",
        incomplete_details=_IncompleteDetails(reason="content_filter"),
    )
    with pytest.raises(OpenAIResponseError, match=r"\(content_filter\)"):
        ensure_response_completed(obj, operation="op")


def test_string_error_raises() -> None:
    with pytest.raises(OpenAIResponseError, match="op failed: bad"):
        ensure_response_completed({"status": "completed", "error": "bad"}, operation="op")


def test_dict_error_uses_message() -> None:
    with pytest.raises(OpenAIResponseError, match="op failed: rate limited"):
        ensure_response_completed(
            {"status": "completed", "error": {"message": "rate limited"}}, operation="op"
        )


def test_dict_error_falls_back_to_code() -> None:
    with pytest.raises(OpenAIResponseError, match="op failed: 429"):
        ensure_response_completed(
            {"status": "completed", "error": {"code": "429"}}, operation="op"
        )


def test_dict_error_falls_back_to_type() -> None:
    with pytest.raises(OpenAIResponseError, match="op failed: server_error"):
        ensure_response_completed(
            {"status": "completed", "error": {"type": "server_error"}}, operation="op"
        )


def test_dict_error_with_no_known_keys_uses_repr() -> None:
    with pytest.raises(OpenAIResponseError) as exc:
        ensure_response_completed(
            {"status": "completed", "error": {"other": "x"}}, operation="op"
        )
    # The whole dict is stringified when none of message/code/type are present.
    assert "{'other': 'x'}" in str(exc.value)


def test_object_error_with_attributes() -> None:
    @dataclass
    class _Err:
        message: str | None = None
        code: str | None = None
        type: str | None = None

    err = _Err(message="object-message")
    with pytest.raises(OpenAIResponseError, match="object-message"):
        ensure_response_completed(_AttrObject(status="completed", error=err), operation="op")


def test_refusal_in_top_level_output() -> None:
    payload = {
        "status": "completed",
        "output": [{"type": "refusal", "refusal": "policy"}],
    }
    with pytest.raises(OpenAIResponseError, match="was refused: policy"):
        ensure_response_completed(payload, operation="op")


def test_refusal_in_top_level_output_falls_back_to_text() -> None:
    payload = {
        "status": "completed",
        "output": [{"type": "refusal", "text": "cannot answer"}],
    }
    with pytest.raises(OpenAIResponseError, match="was refused: cannot answer"):
        ensure_response_completed(payload, operation="op")


def test_refusal_in_top_level_output_no_text_uses_default() -> None:
    payload = {"status": "completed", "output": [{"type": "refusal"}]}
    with pytest.raises(OpenAIResponseError, match="was refused: refusal"):
        ensure_response_completed(payload, operation="op")


def test_refusal_inside_content() -> None:
    payload = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "text", "text": "ok"},
                    {"type": "refusal", "refusal": "nested policy"},
                ],
            }
        ],
    }
    with pytest.raises(OpenAIResponseError, match="was refused: nested policy"):
        ensure_response_completed(payload, operation="op")


def test_output_non_list_is_treated_as_empty() -> None:
    # tuple is iterable list-like; non-list/tuple should be skipped.
    ensure_response_completed({"status": "completed", "output": "not a list"}, operation="op")


def test_output_tuple_iteration() -> None:
    payload = {
        "status": "completed",
        "output": ({"type": "refusal", "refusal": "tuple form"},),
    }
    with pytest.raises(OpenAIResponseError, match="tuple form"):
        ensure_response_completed(payload, operation="op")


# ---------------------------------------------------------------------------
# response_output_text
# ---------------------------------------------------------------------------


def test_response_output_text_strips_whitespace() -> None:
    assert response_output_text({"output_text": "   hello   "}) == "hello"


def test_response_output_text_attr_form() -> None:
    obj = _AttrObject(output_text="from attr")
    assert response_output_text(obj) == "from attr"


def test_response_output_text_reads_nested_response_output() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "hello"},
                    {"type": "output_text", "text": " world"},
                ],
            }
        ]
    }
    assert response_output_text(payload) == "hello world"


def test_response_output_text_missing_field_raises() -> None:
    with pytest.raises(OpenAIResponseError, match="did not include output_text"):
        response_output_text({})


def test_response_output_text_non_string_field_raises() -> None:
    # _string_field only returns when the field is a string, so an int → None.
    with pytest.raises(OpenAIResponseError, match="did not include output_text"):
        response_output_text({"output_text": 42})


def test_response_output_text_empty_string_raises() -> None:
    with pytest.raises(OpenAIResponseError, match="empty text"):
        response_output_text({"output_text": "   "})
