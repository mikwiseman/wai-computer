"""Small safety helpers for OpenAI Responses API results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class OpenAIResponseError(RuntimeError):
    """Raised when OpenAI returns a non-completed or unusable response."""


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _string_field(value: Any, name: str) -> str | None:
    field = _field(value, name)
    return field if isinstance(field, str) else None


def _response_error_message(error: Any) -> str | None:
    if error is None:
        return None
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or error.get("type")
        return str(message) if message else str(error)
    message = _field(error, "message") or _field(error, "code") or _field(error, "type")
    return str(message) if message else str(error)


def ensure_response_completed(response: Any, *, operation: str) -> None:
    """Fail fast when a Responses API result is incomplete, errored, or refused."""
    status = _string_field(response, "status")
    if status and status != "completed":
        details = _field(response, "incomplete_details")
        reason = _field(details, "reason") if details is not None else None
        suffix = f" ({reason})" if reason else ""
        raise OpenAIResponseError(f"{operation} did not complete: {status}{suffix}")

    error_message = _response_error_message(_field(response, "error"))
    if error_message:
        raise OpenAIResponseError(f"{operation} failed: {error_message}")

    for item in _iter_output_items(_field(response, "output")):
        if _field(item, "type") == "refusal":
            refusal = _field(item, "refusal") or _field(item, "text")
            raise OpenAIResponseError(f"{operation} was refused: {refusal or 'refusal'}")
        for content in _iter_output_items(_field(item, "content")):
            if _field(content, "type") == "refusal":
                refusal = _field(content, "refusal") or _field(content, "text")
                raise OpenAIResponseError(f"{operation} was refused: {refusal or 'refusal'}")


def _iter_output_items(value: Any) -> Iterable[Any]:
    if isinstance(value, list | tuple):
        return value
    return ()


def response_output_text(response: Any) -> str:
    """Return stripped ``output_text`` or raise if the model returned no text."""
    text = _string_field(response, "output_text")
    if text is None:
        raise OpenAIResponseError("OpenAI response did not include output_text")
    stripped = text.strip()
    if not stripped:
        raise OpenAIResponseError("OpenAI response returned empty text")
    return stripped
