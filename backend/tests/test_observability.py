"""Observability middleware and sanitization tests."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.api.routes import search as search_routes
from app.core import observability
from app.db import session as db_session_module


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
    assert sanitized["nested"]["token"] == "[redacted-secret]"
    assert sanitized["nested"]["text"].startswith("[redacted-text:")


def test_sanitize_sentry_value_handles_bytes_lists_and_urls():
    payload = {
        "attachment": b"abc",
        "items": ["alice@example.com", "eyJhbGciOiJIUzI1NiJ9.payload.sig"],
        "url": "https://say.waiwai.is/api/search?q=secret",
    }

    sanitized = observability.sanitize_sentry_value(payload, key="payload")

    assert sanitized["attachment"] == "<bytes:3>"
    assert sanitized["items"][0].startswith("[redacted-email:")
    assert sanitized["items"][1] == "[redacted-token]"
    assert sanitized["url"] == "https://say.waiwai.is/api/search"


def test_before_send_redacts_request_user_and_breadcrumb_data():
    event = {
        "request": {
            "url": "https://say.waiwai.is/api/search?q=alice@example.com",
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

    assert sanitized["request"]["url"] == "https://say.waiwai.is/api/search"
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
    monkeypatch.setattr(observability, "get_release_version", lambda: "waisay@test")

    observability.initialize_sentry(dsn="https://example", debug=False, include_fastapi=False)

    assert captured["send_default_pii"] is False
    assert captured["before_send"] is observability._before_send
    assert captured["before_breadcrumb"] is observability._before_breadcrumb
    assert captured["release"] == "waisay@test"


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
        lambda: "waisay@test",
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

        def set_extra(self, key: str, value: object) -> None:
            self.extras[key] = value

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


def test_get_release_version_handles_git_results(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        observability.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="abc123\n"),
    )
    assert observability.get_release_version() == "waisay@abc123"

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
        json={"email": email, "password": "testpassword123"},
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
    async def fake_generate_embedding(_query: str) -> list[float]:
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
