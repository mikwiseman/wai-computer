from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from app.core.cerebras_chat import (
    CerebrasResponseError,
    chat_completion_delta_text,
    chat_completion_parsed,
    chat_completion_text,
    strict_json_response_format,
)


class _Nested(BaseModel):
    name: str


class _Payload(BaseModel):
    title: str
    items: list[_Nested] = Field(max_length=3)


def _chat_response(content: str, *, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        model="gpt-oss-120b",
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ],
    )


def test_strict_json_response_format_sanitizes_pydantic_schema() -> None:
    response_format = strict_json_response_format(_Payload, name="payload")
    schema = response_format["json_schema"]["schema"]

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert "title" not in schema
    assert "maxItems" not in schema["properties"]["items"]
    nested = schema["$defs"]["_Nested"]
    assert nested["additionalProperties"] is False
    assert "title" not in nested


def test_chat_completion_text_reads_content_and_rejects_incomplete() -> None:
    assert chat_completion_text(_chat_response("  Hello  "), operation="test") == "Hello"

    with pytest.raises(CerebrasResponseError, match="length"):
        chat_completion_text(_chat_response("partial", finish_reason="length"), operation="test")


def test_chat_completion_parsed_validates_json_payload() -> None:
    parsed = chat_completion_parsed(
        _chat_response('{"title":"Done","items":[{"name":"A"}]}'),
        _Payload,
        operation="parse",
    )

    assert parsed.title == "Done"
    assert parsed.items[0].name == "A"


def test_chat_completion_delta_text_reads_stream_chunk() -> None:
    event = {
        "choices": [
            {
                "delta": {"content": "Cleaned"},
                "finish_reason": None,
            }
        ]
    }

    assert chat_completion_delta_text(event) == "Cleaned"
