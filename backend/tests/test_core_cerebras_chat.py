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
    assert "title" in schema["properties"]
    assert schema["required"] == ["title", "items"]
    assert "maxItems" not in schema["properties"]["items"]
    nested = schema["$defs"]["_Nested"]
    assert nested["additionalProperties"] is False
    assert "title" not in nested
    assert nested["required"] == ["name"]


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


def test_cerebras_client_bounds_timeout_and_retries(monkeypatch):
    """SDK defaults are timeout=600s + 2 retries — a sick provider could pin
    the single-slot summary worker ~30min per call. Keep each attempt bounded."""
    import app.core.cerebras_chat as module

    monkeypatch.setattr(module, "_cerebras_client", None)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S", (), {"cerebras_api_key": "sk-test", "cerebras_api_base_url": "https://api.cerebras.test/v1"}
        )(),
    )
    client = module.get_cerebras_client()
    assert client.timeout == module.CEREBRAS_REQUEST_TIMEOUT_SECONDS
    assert client.max_retries == module.CEREBRAS_CLIENT_MAX_RETRIES
    monkeypatch.setattr(module, "_cerebras_client", None)
