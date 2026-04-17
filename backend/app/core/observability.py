"""Request-scoped logging and Sentry helpers."""

import hashlib
import logging
import re
import subprocess
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_request_method: ContextVar[str] = ContextVar("request_method", default="-")
_request_path: ContextVar[str] = ContextVar("request_path", default="-")
_user_id: ContextVar[str] = ContextVar("user_id", default="-")
_recording_id: ContextVar[str] = ContextVar("recording_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")
_sentry_initialized = False

EMAIL_PATTERN = re.compile(r"(?P<email>[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
SECRET_KEY_FRAGMENTS = ("token", "password", "secret", "authorization", "cookie")
EMAIL_KEY_FRAGMENTS = ("email",)
TEXT_KEY_FRAGMENTS = (
    "query",
    "question",
    "text",
    "content",
    "transcript",
    "body",
    "html",
    "prompt",
)
FILENAME_KEY_FRAGMENTS = ("filename", "file_name")


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


def fingerprint_text(value: str | None) -> str:
    """Return a stable short hash for correlating sensitive values without logging them."""
    normalized = (value or "").strip()
    if not normalized:
        return "-"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def safe_text_digest(value: str | None, *, label: str = "text") -> str:
    """Return a short, log-friendly digest for sensitive text."""
    normalized = (value or "").strip()
    if not normalized:
        return f"{label}(empty)"
    return f"{label}(len={len(normalized)},sha={fingerprint_text(normalized)})"


def safe_email_metadata(email: str | None) -> dict[str, Any]:
    """Summarize an email address without exposing it."""
    normalized = (email or "").strip().lower()
    return {
        "email_hash": fingerprint_text(normalized),
        "email_length": len(normalized),
    }


def safe_query_metadata(query: str | None) -> dict[str, Any]:
    """Summarize query text without exposing it."""
    normalized = (query or "").strip()
    return {
        "query_hash": fingerprint_text(normalized),
        "query_length": len(normalized),
    }


def safe_filename_metadata(filename: str | None) -> dict[str, Any]:
    """Summarize a filename without exposing the original name."""
    normalized = Path(filename or "").name.strip()
    suffix = Path(normalized).suffix.lower().lstrip(".") if normalized else ""
    return {
        "filename_hash": fingerprint_text(normalized),
        "filename_length": len(normalized),
        "filename_extension": suffix or "none",
    }


def _matches_any_fragment(key: str | None, fragments: tuple[str, ...]) -> bool:
    normalized = (key or "").strip().lower()
    return any(fragment in normalized for fragment in fragments)


def _strip_query_from_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def redact_text(value: str) -> str:
    """Redact obviously sensitive tokens embedded in free-form strings."""
    redacted = EMAIL_PATTERN.sub(
        lambda match: f"[redacted-email:{fingerprint_text(match.group('email').lower())}]",
        value,
    )
    redacted = JWT_PATTERN.sub("[redacted-token]", redacted)
    return redacted


def sanitize_sentry_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize values before they are sent to Sentry."""
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_sentry_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [sanitize_sentry_value(item, key=key) for item in value]

    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    if not isinstance(value, str):
        return value

    normalized = value.strip()

    if _matches_any_fragment(key, SECRET_KEY_FRAGMENTS):
        return "[redacted-secret]"
    if _matches_any_fragment(key, EMAIL_KEY_FRAGMENTS):
        return f"[redacted-email:{fingerprint_text(normalized.lower())}]"
    if _matches_any_fragment(key, FILENAME_KEY_FRAGMENTS):
        meta = safe_filename_metadata(normalized)
        return (
            "[redacted-filename:"
            f"ext={meta['filename_extension']}:sha={meta['filename_hash']}:len={meta['filename_length']}]"
        )
    if _matches_any_fragment(key, TEXT_KEY_FRAGMENTS):
        return f"[redacted-text:len={len(normalized)}:sha={fingerprint_text(normalized)}]"
    if key == "url":
        return _strip_query_from_url(normalized)

    return redact_text(value)


def _sanitize_breadcrumb_payload(breadcrumb: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(breadcrumb)
    if isinstance(sanitized.get("message"), str):
        sanitized["message"] = redact_text(sanitized["message"])
    if "data" in sanitized:
        sanitized["data"] = sanitize_sentry_value(sanitized["data"], key="breadcrumb_data")
    return sanitized


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(event)

    if isinstance(sanitized.get("request"), dict):
        sanitized["request"] = sanitize_sentry_value(sanitized["request"], key="request")
    if "extra" in sanitized:
        sanitized["extra"] = sanitize_sentry_value(sanitized["extra"], key="extra")
    if "contexts" in sanitized:
        sanitized["contexts"] = sanitize_sentry_value(sanitized["contexts"], key="contexts")
    if "user" in sanitized:
        user_payload = sanitize_sentry_value(sanitized["user"], key="user")
        if isinstance(user_payload, dict):
            user_payload.pop("email", None)
        sanitized["user"] = user_payload

    logentry = sanitized.get("logentry")
    if isinstance(logentry, dict):
        if isinstance(logentry.get("message"), str):
            logentry["message"] = redact_text(logentry["message"])
        if isinstance(logentry.get("formatted"), str):
            logentry["formatted"] = redact_text(logentry["formatted"])

    exception = sanitized.get("exception")
    if isinstance(exception, dict) and isinstance(exception.get("values"), list):
        for item in exception["values"]:
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                item["value"] = redact_text(item["value"])

    breadcrumbs = sanitized.get("breadcrumbs")
    if isinstance(breadcrumbs, dict) and isinstance(breadcrumbs.get("values"), list):
        breadcrumbs["values"] = [
            _sanitize_breadcrumb_payload(item) if isinstance(item, dict) else item
            for item in breadcrumbs["values"]
        ]

    return sanitized


def _before_breadcrumb(
    breadcrumb: dict[str, Any],
    _hint: dict[str, Any],
) -> dict[str, Any]:
    return _sanitize_breadcrumb_payload(breadcrumb)


def _sync_sentry_scope() -> None:
    sentry_sdk.set_tag("request_id", _request_id.get())
    sentry_sdk.set_tag("request_method", _request_method.get())
    sentry_sdk.set_tag("request_path", _request_path.get())
    sentry_sdk.set_tag("recording_id", _recording_id.get())
    sentry_sdk.set_tag("session_id", _session_id.get())
    sentry_sdk.set_tag("user_id", _user_id.get())

    user_id = _user_id.get()
    if user_id and user_id != "-":
        sentry_sdk.set_user({"id": user_id})
    else:
        sentry_sdk.set_user(None)


def get_release_version() -> str | None:
    """Derive a release version from the git commit hash when available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"waisay@{result.stdout.strip()}"
    except Exception:
        pass
    return None


def initialize_sentry(
    *,
    dsn: str,
    debug: bool,
    include_fastapi: bool = False,
    include_celery: bool = False,
) -> None:
    """Initialize Sentry once per process with log capture enabled."""
    global _sentry_initialized

    if not dsn or _sentry_initialized:
        return

    integrations = [
        LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR,
        )
    ]

    if include_fastapi:
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        integrations.append(FastApiIntegration())

    if include_celery:
        from sentry_sdk.integrations.celery import CeleryIntegration

        integrations.append(CeleryIntegration(monitor_beat_tasks=True))

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment="production" if not debug else "development",
        release=get_release_version(),
        send_default_pii=False,
        before_send=_before_send,
        before_breadcrumb=_before_breadcrumb,
        integrations=integrations,
    )
    _sentry_initialized = True


def begin_request_context(
    *,
    request_id: str,
    request_method: str,
    request_path: str,
) -> dict[str, Token[str]]:
    """Initialize per-request context and return reset tokens."""
    tokens = {
        "request_id": _request_id.set(request_id),
        "request_method": _request_method.set(request_method),
        "request_path": _request_path.set(request_path),
        "user_id": _user_id.set("-"),
        "recording_id": _recording_id.set("-"),
        "session_id": _session_id.set("-"),
    }
    _sync_sentry_scope()
    return tokens


def end_request_context(tokens: dict[str, Token[str]]) -> None:
    """Restore previous context values after the request is complete."""
    _session_id.reset(tokens["session_id"])
    _recording_id.reset(tokens["recording_id"])
    _user_id.reset(tokens["user_id"])
    _request_path.reset(tokens["request_path"])
    _request_method.reset(tokens["request_method"])
    _request_id.reset(tokens["request_id"])
    _sync_sentry_scope()


def bind_user_context(user_id: str | None) -> None:
    """Attach the authenticated user id to subsequent logs."""
    _user_id.set(user_id or "-")
    _sync_sentry_scope()


def bind_recording_context(recording_id: str | None) -> None:
    """Attach the active recording id to subsequent logs."""
    _recording_id.set(recording_id or "-")
    _sync_sentry_scope()


def bind_session_context(session_id: str | None) -> None:
    """Attach a request/session identifier to subsequent logs."""
    _session_id.set(session_id or "-")
    _sync_sentry_scope()


def add_sentry_breadcrumb(
    *,
    category: str,
    message: str,
    data: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """Record a breadcrumb after sanitizing attached metadata."""
    sentry_sdk.add_breadcrumb(
        category=category,
        message=redact_text(message),
        data=sanitize_sentry_value(data or {}, key="breadcrumb_data"),
        level=level,
    )


def capture_sentry_exception(error: Exception, *, extras: dict[str, Any] | None = None) -> None:
    """Capture an exception with sanitized extras."""
    if extras:
        with sentry_sdk.new_scope() as scope:
            sanitized = sanitize_sentry_value(extras, key="extras")
            for key, value in sanitized.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_exception(error)
        return

    sentry_sdk.capture_exception(error)
