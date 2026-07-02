"""Cerebras Chat Completions helpers for text and strict JSON outputs."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import get_settings

_cerebras_client: openai.AsyncOpenAI | None = None
SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Cerebras completions normally finish in seconds; the OpenAI SDK defaults are
# timeout=600s with 2 internal retries, so a sick provider could pin the
# single-slot summary worker for ~30 minutes per call (and stack under Celery's
# own retries). Bound each attempt and keep one transient retry.
CEREBRAS_REQUEST_TIMEOUT_SECONDS = 120.0
CEREBRAS_CLIENT_MAX_RETRIES = 1


class CerebrasResponseError(RuntimeError):
    """Raised when Cerebras returns an unusable chat completion."""


def get_cerebras_client() -> openai.AsyncOpenAI:
    """Return a process-wide AsyncOpenAI client pointed at Cerebras."""
    global _cerebras_client
    if _cerebras_client is None:
        settings = get_settings()
        _cerebras_client = openai.AsyncOpenAI(
            api_key=settings.cerebras_api_key,
            base_url=settings.cerebras_api_base_url,
            timeout=CEREBRAS_REQUEST_TIMEOUT_SECONDS,
            max_retries=CEREBRAS_CLIENT_MAX_RETRIES,
        )
    return _cerebras_client


def strict_json_response_format(schema_model: type[BaseModel], *, name: str) -> dict[str, Any]:
    """Build a Cerebras strict ``response_format`` from a Pydantic schema."""
    schema = _sanitize_json_schema(schema_model.model_json_schema())
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def chat_completion_text(response: Any, *, operation: str) -> str:
    """Extract stripped assistant text from a Chat Completion response."""
    _ensure_chat_completion_finished(response, operation=operation)
    choice = _first_choice(response)
    message = _field(choice, "message")
    content = _message_content_text(message)
    stripped = content.strip()
    if not stripped:
        raise CerebrasResponseError(f"{operation} returned empty text")
    return stripped


def chat_completion_parsed(
    response: Any,
    schema_model: type[SchemaT],
    *,
    operation: str,
) -> SchemaT:
    """Extract, JSON-decode, and validate a strict structured response."""
    text = chat_completion_text(response, operation=operation)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CerebrasResponseError(f"{operation} returned invalid JSON") from exc
    try:
        return schema_model.model_validate(payload)
    except ValidationError as exc:
        raise CerebrasResponseError(f"{operation} returned invalid schema payload") from exc


def chat_completion_model(response: Any, fallback: str | None = None) -> str | None:
    """Return the provider-reported model, if present."""
    model = _field(response, "model")
    return model if isinstance(model, str) and model else fallback


def chat_completion_delta_text(event: Any) -> str:
    """Extract assistant delta text from one Chat Completion stream event."""
    choice = _first_choice(event, required=False)
    if choice is None:
        return ""
    delta = _field(choice, "delta")
    return _message_content_text(delta)


def chat_completion_finish_reason(event: Any) -> str | None:
    """Extract a stream event's finish reason, if it carries one."""
    choice = _first_choice(event, required=False)
    if choice is None:
        return None
    reason = _field(choice, "finish_reason")
    return reason if isinstance(reason, str) and reason else None


def chat_completion_usage_response(
    *,
    model: str | None,
    usage: Any,
    response_id: str | None = None,
) -> dict[str, Any]:
    """Wrap stream usage in a normal response-like object for the usage ledger."""
    return {"id": response_id, "model": model, "usage": usage}


def _ensure_chat_completion_finished(response: Any, *, operation: str) -> None:
    choice = _first_choice(response)
    finish_reason = _field(choice, "finish_reason")
    if finish_reason and finish_reason != "stop":
        raise CerebrasResponseError(f"{operation} did not complete: {finish_reason}")


def _first_choice(response: Any, *, required: bool = True) -> Any:
    choices = _field(response, "choices")
    if isinstance(choices, list | tuple) and choices:
        return choices[0]
    if required:
        raise CerebrasResponseError("Cerebras response did not include choices")
    return None


def _message_content_text(message: Any) -> str:
    content = _field(message, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list | tuple):
        parts: list[str] = []
        for item in content:
            text = _field(item, "text") or _field(item, "content")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _sanitize_json_schema(value: Any) -> Any:
    """Adapt Pydantic JSON Schema to Cerebras strict-mode's supported subset."""
    unsupported_keys = {
        "default",
        "description",
        "examples",
        "format",
        "maxItems",
        "minItems",
        "pattern",
        "title",
    }
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, raw in value.items():
            if key in unsupported_keys:
                continue
            if key in {"$defs", "definitions", "properties"} and isinstance(raw, dict):
                cleaned[key] = {
                    property_name: _sanitize_json_schema(property_schema)
                    for property_name, property_schema in raw.items()
                }
                continue
            cleaned[key] = _sanitize_json_schema(raw)
        if cleaned.get("type") == "object":
            properties = cleaned.get("properties")
            if isinstance(properties, dict):
                cleaned["required"] = list(properties)
            cleaned["additionalProperties"] = False
        return cleaned
    if isinstance(value, list):
        return [_sanitize_json_schema(item) for item in value]
    if isinstance(value, Iterable) and not isinstance(value, str | bytes):
        return list(value)
    return value
