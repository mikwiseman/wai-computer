"""Observability middleware and sanitization tests."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient

from app.api.routes import search as search_routes
from app.core import observability
from app.db import session as db_session_module
from tests.conftest import LEGAL_ACCEPTANCE


def test_configure_logging_is_idempotent():
    handler = logging.StreamHandler()
    handler.filters = []
    logger = logging.Logger("observability-test")
    logger.handlers = [handler]

    original_get_logger = logging.getLogger
    logging.getLogger = lambda: logger  # type: ignore[assignment]
    try:
        observability.configure_logging()
        observability.configure_logging()
    finally:
        logging.getLogger = original_get_logger  # type: ignore[assignment]

    filters = [
        flt
        for flt in handler.filters
        if isinstance(flt, observability.RequestContextFilter)
    ]
    assert len(filters) == 1
    redacting_filters = [
        flt
        for flt in handler.filters
        if isinstance(flt, observability.RedactingLogFilter)
    ]
    assert len(redacting_filters) == 1


def test_configure_logging_supports_json_formatter():
    handler = logging.StreamHandler()
    handler.filters = []
    logger = logging.Logger("observability-json-test")
    logger.handlers = [handler]

    original_get_logger = logging.getLogger
    logging.getLogger = lambda: logger  # type: ignore[assignment]
    try:
        observability.configure_logging(log_format="json")
    finally:
        logging.getLogger = original_get_logger  # type: ignore[assignment]

    assert isinstance(handler.formatter, observability.JsonLogFormatter)
    assert any(isinstance(item, observability.RequestContextFilter) for item in handler.filters)
    assert any(isinstance(item, observability.RedactingLogFilter) for item in handler.filters)


def test_redact_text_removes_telegram_bot_tokens_and_secret_queries():
    redacted = observability.redact_text(
        "POST https://api.telegram.org/bot123456:ABC-SECRET/sendMessage "
        "GET https://api.telegram.org/file/bot123456:ABC-SECRET/voice/file.oga "
        "https://wai.computer/auth/app?token=secret&client=macos"
    )

    assert "123456:ABC-SECRET" not in redacted
    assert "token=secret" not in redacted
    assert "https://api.telegram.org/bot[redacted-token]/sendMessage" in redacted
    assert "https://api.telegram.org/file/bot[redacted-token]/voice/file.oga" in redacted
    assert "token=[redacted-secret]" in redacted


def test_redact_text_uses_shared_secret_patterns():
    redacted = observability.redact_text(
        "openai sk-abcdefghijklmnopqrstuvwxyz "
        "github ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "bearer Bearer abcdefghijklmnopqrstuvwxyz123456 "
        "aws AKIAABCDEFGHIJKLMNOP "
        "key -----BEGIN PRIVATE KEY-----"
    )

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "Bearer abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "-----BEGIN PRIVATE KEY-----" not in redacted
    assert "[REDACTED:openai_key]" in redacted
    assert "[REDACTED:github_token]" in redacted
    assert "[REDACTED:bearer_token]" in redacted
    assert "[REDACTED:aws_access_key]" in redacted
    assert "[REDACTED:private_key]" in redacted


def test_redacting_log_filter_sanitizes_message_and_arguments():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "telegram url %s",
        ("https://api.telegram.org/bot123456:ABC-SECRET/sendMessage",),
        None,
    )

    assert observability.RedactingLogFilter().filter(record)

    assert "ABC-SECRET" not in record.getMessage()
    assert "bot[redacted-token]" in record.getMessage()


def test_redacting_log_filter_sanitizes_httpx_url_arguments():
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        'HTTP Request: %s %s "%s"',
        (
            "GET",
            httpx.URL("https://api.telegram.org/file/bot123456:ABC-SECRET/voice/file.oga"),
            "HTTP/1.1 200 OK",
        ),
        None,
    )

    assert observability.RedactingLogFilter().filter(record)

    assert "ABC-SECRET" not in record.getMessage()
    assert "https://api.telegram.org/file/bot[redacted-token]/voice/file.oga" in record.getMessage()


def test_json_log_formatter_outputs_safe_structured_payload():
    record = logging.LogRecord(
        "test",
        logging.WARNING,
        __file__,
        1,
        "failed request for %s",
        ("alice@example.com",),
        None,
    )
    record.request_id = "req-1"
    record.request_method = "POST"
    record.request_path = "/api/recordings"
    record.user_id = "user-1"
    record.recording_id = "rec-1"
    record.session_id = "sess-1"
    observability.RedactingLogFilter().filter(record)

    formatted = observability.JsonLogFormatter().format(record)

    assert '"level":"WARNING"' in formatted
    assert '"request_id":"req-1"' in formatted
    assert "alice@example.com" not in formatted
    assert "[redacted-email:" in formatted


def test_json_log_formatter_redacts_exception_text():
    try:
        raise RuntimeError("alice@example.com failed")
    except RuntimeError:
        exc_info = __import__("sys").exc_info()

    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "upload failed",
        (),
        exc_info,
    )
    formatted = observability.JsonLogFormatter().format(record)

    assert "alice@example.com" not in formatted
    assert "[redacted-email:" in formatted


def test_redacting_log_filter_sanitizes_nested_arguments():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "payload %s",
        (
            {
                "email": "alice@example.com",
                "items": ["https://wai.computer/auth/app?token=secret"],
                "nested": ("eyJabc.def.ghi",),
            },
        ),
        None,
    )

    assert observability.RedactingLogFilter().filter(record)

    message = record.getMessage()
    assert "alice@example.com" not in message
    assert "token=secret" not in message
    assert "eyJabc.def.ghi" not in message


def test_safe_metadata_helpers_do_not_expose_raw_values():
    email_meta = observability.safe_email_metadata("Alice.Private@example.com")
    query_meta = observability.safe_query_metadata("where did Alice mention the budget?")
    filename_meta = observability.safe_filename_metadata("Alice Budget Notes.m4a")

    assert email_meta["email_hash"] != "-"
    assert email_meta["email_length"] == len("alice.private@example.com")
    assert query_meta["query_length"] == len("where did Alice mention the budget?")
    assert filename_meta["filename_extension"] == "m4a"
    assert filename_meta["filename_hash"] != "-"


def test_safe_helpers_handle_empty_values():
    assert observability.fingerprint_text(None) == "-"
    assert observability.safe_text_digest("", label="query") == "query(empty)"
    assert observability.safe_filename_metadata(None)["filename_extension"] == "none"


def test_sanitize_sentry_value_redacts_sensitive_payloads():
    payload = {
        "email": "alice@example.com",
        "password": "secret-password",
        "query": "Alice salary details",
        "filename": "alice-comp-plan.wav",
        "Authorization": "Bearer abc",
        "reason": "Alice@example.com discussed the token",
        "error": "Alice salary details failed",
        "detail": "alice@example.com salary details",
        "description": "Alice private transcript description",
        "message": "Alice private message",
        "nested": {
            "token": "jwt-token",
            "text": "Alice@example.com said hello",
        },
    }

    sanitized = observability.sanitize_sentry_value(payload, key="payload")

    assert sanitized["email"].startswith("[redacted-email:")
    assert sanitized["password"] == "[redacted-secret]"
    assert sanitized["query"].startswith("[redacted-text:")
    assert sanitized["filename"].startswith("[redacted-filename:")
    assert sanitized["Authorization"] == "[redacted-secret]"
    assert sanitized["reason"].startswith("[redacted-text:")
    assert sanitized["error"].startswith("[redacted-text:")
    assert sanitized["detail"].startswith("[redacted-text:")
    assert sanitized["description"].startswith("[redacted-text:")
    assert sanitized["message"].startswith("[redacted-text:")
    assert sanitized["nested"]["token"] == "[redacted-secret]"
    assert sanitized["nested"]["text"].startswith("[redacted-text:")


def test_sanitize_sentry_value_handles_bytes_lists_and_urls():
    payload = {
        "attachment": b"abc",
        "items": ["alice@example.com", "eyJhbGciOiJIUzI1NiJ9.payload.sig"],
        "url": "https://wai.computer/api/search?q=secret",
    }

    sanitized = observability.sanitize_sentry_value(payload, key="payload")

    assert sanitized["attachment"] == "<bytes:3>"
    assert sanitized["items"][0].startswith("[redacted-email:")
    assert sanitized["items"][1] == "[redacted-token]"
    assert sanitized["url"] == "https://wai.computer/api/search"


def test_before_send_redacts_request_user_and_breadcrumb_data():
    event = {
        "request": {
            "url": "https://wai.computer/api/search?q=alice@example.com",
            "headers": {
                "Authorization": "Bearer abc",
                "Cookie": "session=123",
            },
            "data": {
                "email": "alice@example.com",
                "query": "Alice comp details",
            },
        },
        "user": {"id": "user-1", "email": "alice@example.com"},
        "breadcrumbs": {
            "values": [
                {
                    "category": "search",
                    "message": "query alice@example.com",
                    "data": {"query": "Alice comp details"},
                }
            ]
        },
        "logentry": {"message": "login failed for alice@example.com"},
    }

    sanitized = observability._before_send(event, {})

    assert sanitized["request"]["url"] == "https://wai.computer/api/search"
    assert sanitized["request"]["headers"]["Authorization"] == "[redacted-secret]"
    assert sanitized["request"]["headers"]["Cookie"] == "[redacted-secret]"
    assert sanitized["request"]["data"]["email"].startswith("[redacted-email:")
    assert sanitized["request"]["data"]["query"].startswith("[redacted-text:")
    assert "email" not in sanitized["user"]
    assert "[redacted-email:" in sanitized["breadcrumbs"]["values"][0]["message"]
    assert sanitized["breadcrumbs"]["values"][0]["data"]["query"].startswith("[redacted-text:")
    assert "[redacted-email:" in sanitized["logentry"]["message"]


def test_before_send_redacts_extra_contexts_and_exception_values():
    event = {
        "extra": {"query": "Alice salary details", "attachment": b"abc"},
        "contexts": {"trace": {"email": "alice@example.com"}},
        "logentry": {"formatted": "alice@example.com triggered failure"},
        "exception": {"values": [{"value": "token eyJabc.def.ghi leaked"}]},
    }

    sanitized = observability._before_send(event, {})

    assert sanitized["extra"]["query"].startswith("[redacted-text:")
    assert sanitized["extra"]["attachment"] == "<bytes:3>"
    assert sanitized["contexts"]["trace"]["email"].startswith("[redacted-email:")
    assert "[redacted-email:" in sanitized["logentry"]["formatted"]
    assert sanitized["exception"]["values"][0]["value"] == "token [redacted-token] leaked"


def test_initialize_sentry_registers_sanitizers(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_init(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(observability.sentry_sdk, "init", fake_init)
    monkeypatch.setattr(observability, "_sentry_initialized", False)
    monkeypatch.setattr(observability, "get_release_version", lambda: "waicomputer@test")

    observability.initialize_sentry(dsn="https://example", debug=False, include_fastapi=False)

    assert captured["send_default_pii"] is False
    assert captured["before_send"] is observability._before_send
    assert captured["before_breadcrumb"] is observability._before_breadcrumb
    assert captured["release"] == "waicomputer@test"
    assert captured["enable_logs"] is True
    assert captured["traces_sample_rate"] == 0.1
    assert captured["profiles_sample_rate"] == 0.1


def test_initialize_sentry_without_dsn_records_runtime(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(observability, "_sentry_initialized", False)
    monkeypatch.setattr(observability, "get_release_version", lambda: "waicomputer@test")

    observability.initialize_sentry(
        dsn="",
        debug=True,
        traces_sample_rate=0.2,
        profiles_sample_rate=0.3,
    )

    runtime = observability.get_sentry_runtime()
    assert captured == {}
    assert runtime["configured"] is False
    assert runtime["release"] == "waicomputer@test"
    assert runtime["environment"] == "development"
    assert runtime["traces_sample_rate"] == 0.2
    assert runtime["profiles_sample_rate"] == 0.3


def test_initialize_sentry_includes_optional_integrations(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeFastAPIIntegration:
        pass

    class FakeCeleryIntegration:
        def __init__(self, *, monitor_beat_tasks: bool):
            self.monitor_beat_tasks = monitor_beat_tasks

    def fake_init(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(observability.sentry_sdk, "init", fake_init)
    monkeypatch.setattr(observability, "_sentry_initialized", False)
    monkeypatch.setattr(
        observability,
        "get_release_version",
        lambda: "waicomputer@test",
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "sentry_sdk.integrations.fastapi",
        SimpleNamespace(FastApiIntegration=FakeFastAPIIntegration),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "sentry_sdk.integrations.celery",
        SimpleNamespace(CeleryIntegration=FakeCeleryIntegration),
    )

    observability.initialize_sentry(
        dsn="https://example",
        debug=True,
        include_fastapi=True,
        include_celery=True,
    )

    integrations = captured["integrations"]
    assert any(isinstance(item, FakeFastAPIIntegration) for item in integrations)
    assert any(
        isinstance(item, FakeCeleryIntegration) and item.monitor_beat_tasks is True
        for item in integrations
    )
    assert captured["environment"] == "development"


def test_request_context_syncs_sentry_scope(monkeypatch: pytest.MonkeyPatch):
    tags: list[tuple[str, str]] = []
    users: list[dict[str, str] | None] = []

    monkeypatch.setattr(
        observability.sentry_sdk,
        "set_tag",
        lambda key, value: tags.append((key, value)),
    )
    monkeypatch.setattr(observability.sentry_sdk, "set_user", lambda value: users.append(value))

    tokens = observability.begin_request_context(
        request_id="req-1",
        request_method="POST",
        request_path="/api/auth/login",
    )
    observability.bind_user_context("user-123")
    observability.bind_recording_context("rec-456")
    observability.bind_session_context("sess-789")
    observability.end_request_context(tokens)

    assert ("request_id", "req-1") in tags
    assert ("request_method", "POST") in tags
    assert ("request_path", "/api/auth/login") in tags
    assert ("user_id", "user-123") in tags
    assert ("recording_id", "rec-456") in tags
    assert ("session_id", "sess-789") in tags
    assert {"id": "user-123"} in users
    assert users[-1] is None


def test_add_sentry_breadcrumb_sanitizes_message_and_data(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_add_breadcrumb(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(observability.sentry_sdk, "add_breadcrumb", fake_add_breadcrumb)

    observability.add_sentry_breadcrumb(
        category="auth",
        message="login for alice@example.com",
        data={"email": "alice@example.com", "query": "secret question"},
    )

    assert captured["category"] == "auth"
    assert "[redacted-email:" in captured["message"]
    assert captured["data"]["email"].startswith("[redacted-email:")
    assert captured["data"]["query"].startswith("[redacted-text:")


def test_before_breadcrumb_redacts_message_and_payload():
    breadcrumb = {
        "category": "auth",
        "message": "password reset for alice@example.com",
        "data": {"email": "alice@example.com", "filename": "alice-private-notes.wav"},
    }

    sanitized = observability._before_breadcrumb(breadcrumb, {})

    assert sanitized["message"].startswith("password reset for [redacted-email:")
    assert sanitized["data"]["email"].startswith("[redacted-email:")
    assert sanitized["data"]["filename"].startswith("[redacted-filename:")


def test_capture_sentry_exception_sanitizes_extras(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class DummyScope:
        def __init__(self) -> None:
            self.extras: dict[str, object] = {}
            self.tags: dict[str, str] = {}

        def set_extra(self, key: str, value: object) -> None:
            self.extras[key] = value

        def set_tag(self, key: str, value: str) -> None:
            self.tags[key] = value

    class DummyScopeManager:
        def __enter__(self) -> DummyScope:
            scope = DummyScope()
            captured["scope"] = scope
            return scope

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_capture_exception(error: Exception) -> None:
        captured["error"] = error

    monkeypatch.setattr(observability.sentry_sdk, "new_scope", lambda: DummyScopeManager())
    monkeypatch.setattr(observability.sentry_sdk, "capture_exception", fake_capture_exception)

    error = RuntimeError("login failed for alice@example.com")
    observability.capture_sentry_exception(
        error,
        extras={
            "alert_code": "recording.processing.failed",
            "email": "alice@example.com",
            "query": "Alice salary details",
            "Authorization": "Bearer secret",
        },
    )

    scope = captured["scope"]
    assert isinstance(scope, DummyScope)
    assert scope.extras["email"].startswith("[redacted-email:")
    assert scope.extras["query"].startswith("[redacted-text:")
    assert scope.extras["Authorization"] == "[redacted-secret]"
    assert scope.tags["alert_code"] == "recording.processing.failed"
    assert captured["error"] is error


def test_capture_sentry_exception_without_extras(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        observability.sentry_sdk,
        "capture_exception",
        lambda error: captured.setdefault("error", error),
    )

    error = RuntimeError("plain failure")
    observability.capture_sentry_exception(error)

    assert captured["error"] is error


def test_capture_sentry_message_sanitizes_message_and_extras(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class DummyScope:
        def __init__(self) -> None:
            self.extras: dict[str, object] = {}
            self.tags: dict[str, str] = {}

        def set_extra(self, key: str, value: object) -> None:
            self.extras[key] = value

        def set_tag(self, key: str, value: str) -> None:
            self.tags[key] = value

    class DummyScopeManager:
        def __enter__(self) -> DummyScope:
            scope = DummyScope()
            captured["scope"] = scope
            return scope

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_capture_message(message: str, *, level: str) -> None:
        captured["message"] = message
        captured["level"] = level

    monkeypatch.setattr(observability.sentry_sdk, "new_scope", lambda: DummyScopeManager())
    monkeypatch.setattr(observability.sentry_sdk, "capture_message", fake_capture_message)

    observability.capture_sentry_message(
        "coverage failed for alice@example.com",
        level="warning",
        extras={
            "alert_code": "recording.transcript.low_coverage",
            "error": "Alice salary details failed",
            "filename": "alice-private.wav",
        },
    )

    scope = captured["scope"]
    assert isinstance(scope, DummyScope)
    assert "[redacted-email:" in captured["message"]
    assert captured["level"] == "warning"
    assert scope.tags["alert_code"] == "recording.transcript.low_coverage"
    assert scope.extras["error"].startswith("[redacted-text:")
    assert scope.extras["filename"].startswith("[redacted-filename:")


def test_capture_sentry_message_without_extras(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        observability.sentry_sdk,
        "capture_message",
        lambda message, *, level: captured.update({"message": message, "level": level}),
    )

    observability.capture_sentry_message("alert for alice@example.com", level="error")

    assert "[redacted-email:" in captured["message"]
    assert captured["level"] == "error"


def test_capture_sentry_anomaly_sets_alert_code_tag_and_breadcrumb(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {"breadcrumbs": []}

    class DummyScope:
        def __init__(self) -> None:
            self.extras: dict[str, object] = {}
            self.tags: dict[str, str] = {}

        def set_extra(self, key: str, value: object) -> None:
            self.extras[key] = value

        def set_tag(self, key: str, value: str) -> None:
            self.tags[key] = value

    class DummyScopeManager:
        def __enter__(self) -> DummyScope:
            scope = DummyScope()
            captured["scope"] = scope
            return scope

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(observability.sentry_sdk, "new_scope", lambda: DummyScopeManager())
    monkeypatch.setattr(
        observability.sentry_sdk,
        "capture_message",
        lambda message, *, level: captured.update({"message": message, "level": level}),
    )
    monkeypatch.setattr(
        observability.sentry_sdk,
        "add_breadcrumb",
        lambda **kwargs: captured["breadcrumbs"].append(kwargs),
    )

    observability.capture_sentry_anomaly(
        "recording.file_stt.slow",
        "File transcription is slow for alice@example.com",
        category="recording",
        extras={
            "query": "private search terms",
            "filename": "secret-meeting.wav",
            "latency_ms": 120_500,
        },
    )

    scope = captured["scope"]
    assert isinstance(scope, DummyScope)
    assert captured["message"].startswith("File transcription is slow for [redacted-email:")
    assert captured["level"] == "warning"
    assert scope.tags["alert_code"] == "recording.file_stt.slow"
    assert scope.extras["alert_code"] == "recording.file_stt.slow"
    assert scope.extras["query"].startswith("[redacted-text:")
    assert scope.extras["filename"].startswith("[redacted-filename:")
    assert captured["breadcrumbs"][-1]["category"] == "recording"
    assert captured["breadcrumbs"][-1]["data"]["alert_code"] == "recording.file_stt.slow"


def test_get_release_version_handles_git_results(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        observability.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="abc123\n"),
    )
    assert observability.get_release_version() == "waicomputer-backend@abc123"

    monkeypatch.setattr(
        observability.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert observability.get_release_version() is None


def test_get_release_version_handles_subprocess_errors(monkeypatch: pytest.MonkeyPatch):
    def blow_up(*args, **kwargs):
        raise RuntimeError("git missing")

    monkeypatch.setattr(observability.subprocess, "run", blow_up)
    assert observability.get_release_version() is None


@pytest.mark.asyncio
async def test_health_echoes_request_id(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class DummySession:
        async def __aenter__(self) -> "DummySession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def execute(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(db_session_module, "async_session_maker", lambda: DummySession())

    response = await client.get("/health", headers={"X-Request-ID": "req-health-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-health-123"


@pytest.mark.asyncio
async def test_request_id_header_present_on_unauthorized_response(client: AsyncClient):
    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_auth_logs_do_not_expose_email(client: AsyncClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)
    email = "alice.private@example.com"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "testpassword123", **LEGAL_ACCEPTANCE},
    )
    caplog.clear()

    response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert email not in caplog.text
    assert "email(len=" in caplog.text
    assert "reason=bad_password" in caplog.text


@pytest.mark.asyncio
async def test_search_logs_do_not_expose_query(
    client: AsyncClient,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_generate_embedding(_query: str, **_: object) -> list[float]:
        return [0.0, 0.0, 0.0]

    monkeypatch.setattr(search_routes, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(search_routes, "format_embedding", lambda _embedding: "[0,0,0]")

    query = "where did alice@example.com mention compensation?"
    caplog.set_level(logging.INFO)
    response = await client.get("/api/search", params={"q": query}, headers=auth_headers)

    assert response.status_code == 200
    assert query not in caplog.text
    assert "query(len=" in caplog.text
    assert "hybrid_search" in caplog.text


@pytest.mark.asyncio
async def test_upload_logs_do_not_expose_filename(
    client: AsyncClient,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
):
    create_response = await client.post(
        "/api/recordings",
        json={"title": "Upload Test", "type": "note"},
        headers=auth_headers,
    )
    recording_id = create_response.json()["id"]
    private_filename = "alice.private@example.com-notes.txt"

    caplog.set_level(logging.INFO)
    response = await client.post(
        f"/api/recordings/{recording_id}/upload",
        headers=auth_headers,
        files={"file": (private_filename, b"hello", "text/plain")},
    )

    assert response.status_code == 415
    assert private_filename not in caplog.text
    assert "filename(len=" in caplog.text


# --- generic Sentry event -> Telegram ops relay (task #18) -------------------
def _capture_forwarded(monkeypatch):
    """Patch notify_ops in the observability module and capture its calls."""
    calls: list[dict] = []
    monkeypatch.setenv("OPS_FORWARD_GENERIC_ERRORS", "1")

    def _fake_notify_ops(**kwargs):
        calls.append(kwargs)

    # _forward_generic_event_to_ops imports notify_ops lazily from ops_alerts.
    from app.core import ops_alerts

    monkeypatch.setattr(ops_alerts, "notify_ops", _fake_notify_ops)
    return calls


def test_generic_error_event_forwarded_to_ops(monkeypatch):
    calls = _capture_forwarded(monkeypatch)
    event = {
        "level": "error",
        "transaction": "POST /api/recordings",
        "exception": {"values": [{"type": "ValueError", "value": "boom happened"}]},
    }
    out = observability._before_send(event, {})
    assert out is not None  # event is still delivered to Sentry
    assert len(calls) == 1
    assert calls[0]["alert_code"] == "sentry.ValueError"
    assert "ValueError" in calls[0]["message"]
    assert calls[0]["extras"]["transaction"] == "POST /api/recordings"
    assert calls[0]["level"] == "error"


def test_anomaly_event_with_alert_code_not_double_forwarded(monkeypatch):
    """Events from capture_sentry_anomaly carry an alert_code in extra and already
    notify ops directly — the relay must SKIP them to avoid double-alerting."""
    calls = _capture_forwarded(monkeypatch)
    event = {
        "level": "warning",
        "extra": {"alert_code": "recording.transcription.guard_refused"},
        "exception": {"values": [{"type": "ValueError", "value": "x"}]},
    }
    observability._before_send(event, {})
    assert calls == []


def test_non_error_level_event_not_forwarded(monkeypatch):
    calls = _capture_forwarded(monkeypatch)
    observability._before_send({"level": "info", "logentry": {"message": "hi"}}, {})
    assert calls == []


def test_generic_forward_uses_logentry_when_no_exception(monkeypatch):
    calls = _capture_forwarded(monkeypatch)
    event = {"level": "fatal", "logentry": {"formatted": "worker died"}}
    observability._before_send(event, {})
    assert len(calls) == 1
    assert calls[0]["alert_code"] == "sentry.Error"
    assert "worker died" in calls[0]["message"]
    assert calls[0]["level"] == "fatal"


def test_generic_forward_never_raises_on_bad_notify(monkeypatch):
    from app.core import ops_alerts

    def _boom(**_kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(ops_alerts, "notify_ops", _boom)
    # must return the event regardless (Sentry delivery must not break)
    out = observability._before_send(
        {"level": "error", "exception": {"values": [{"type": "E", "value": "v"}]}}, {}
    )
    assert out is not None
