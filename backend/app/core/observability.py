"""Request-scoped logging helpers."""

import logging
from contextvars import ContextVar, Token

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_request_method: ContextVar[str] = ContextVar("request_method", default="-")
_request_path: ContextVar[str] = ContextVar("request_path", default="-")
_user_id: ContextVar[str] = ContextVar("user_id", default="-")
_recording_id: ContextVar[str] = ContextVar("recording_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")


class RequestContextFilter(logging.Filter):
    """Inject request-scoped identifiers into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.request_method = _request_method.get()
        record.request_path = _request_path.get()
        record.user_id = _user_id.get()
        record.recording_id = _recording_id.get()
        record.session_id = _session_id.get()
        return True


def configure_logging() -> None:
    """Attach request-context filtering to the root logger once."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if any(isinstance(existing, RequestContextFilter) for existing in handler.filters):
            continue
        handler.addFilter(RequestContextFilter())


def begin_request_context(
    *,
    request_id: str,
    request_method: str,
    request_path: str,
) -> dict[str, Token[str]]:
    """Initialize per-request context and return reset tokens."""
    return {
        "request_id": _request_id.set(request_id),
        "request_method": _request_method.set(request_method),
        "request_path": _request_path.set(request_path),
        "user_id": _user_id.set("-"),
        "recording_id": _recording_id.set("-"),
        "session_id": _session_id.set("-"),
    }


def end_request_context(tokens: dict[str, Token[str]]) -> None:
    """Restore previous context values after the request is complete."""
    _session_id.reset(tokens["session_id"])
    _recording_id.reset(tokens["recording_id"])
    _user_id.reset(tokens["user_id"])
    _request_path.reset(tokens["request_path"])
    _request_method.reset(tokens["request_method"])
    _request_id.reset(tokens["request_id"])


def bind_user_context(user_id: str | None) -> None:
    """Attach the authenticated user id to subsequent logs."""
    _user_id.set(user_id or "-")


def bind_recording_context(recording_id: str | None) -> None:
    """Attach the active recording id to subsequent logs."""
    _recording_id.set(recording_id or "-")


def bind_session_context(session_id: str | None) -> None:
    """Attach a request/session identifier to subsequent logs."""
    _session_id.set(session_id or "-")
