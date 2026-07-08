"""Tests for app.main lifespan warnings and middleware error handling."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Lifespan warnings — combined into a single invocation per test to avoid
# cross-test state pollution from the module-level mcp_asgi_app.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "StreamableHTTPSessionManager singleton prevents re-entering lifespan "
        "in a process; this test conflicts with other tests that also invoke "
        "the FastAPI app. Run individually: pytest tests/test_main_lifespan_middleware.py::"
        "test_lifespan_emits_all_warnings_when_everything_unconfigured"
    )
)
@pytest.mark.asyncio
async def test_lifespan_emits_all_warnings_when_everything_unconfigured(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All 4 missing-credential branches + the unsupported-provider branch fire
    in a single lifespan when everything is misconfigured."""
    from app import main
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "realtime_voice_provider", "openai", raising=False)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "ok", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "cerebras_api_key", "", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "redis_url", "", raising=False)
    monkeypatch.setattr(main, "app_settings", settings)

    caplog.set_level(logging.WARNING, logger="app.main")
    async with main.lifespan(main.app):
        pass

    messages = " ".join(r.message for r in caplog.records)
    assert "unsupported" in messages.lower()
    assert "OPENAI_API_KEY" in messages
    assert "CEREBRAS_API_KEY" in messages
    assert "RESEND_API_KEY" in messages
    assert "REDIS_URL" in messages


# Note: the elevenlabs-missing-key warning branch (provider == elevenlabs AND
# elevenlabs_api_key == "") is exercised when the integration test suite runs
# the app with no API key, OR when the prod app boots without configuration —
# it cannot share a process with the unsupported-provider test above because
# StreamableHTTPSessionManager raises on a second .run() of the same instance.


# ---------------------------------------------------------------------------
# Health + root endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_endpoint_returns_app_info() -> None:
    from app import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "WaiComputer API"
    assert body["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_endpoint_returns_healthy_when_db_ok(db_session: Any) -> None:
    """db_session fixture from conftest already establishes a real test DB
    connection — so /health should report healthy."""
    from app import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert "schema_revision" in body
    assert "git_sha" in body
    assert body["git_dirty"] is False


def test_system_routes_are_registered_once() -> None:
    from app import main

    counts: dict[tuple[str, str], int] = {}

    def _collect(routes: list, prefix: str) -> None:
        for route in routes:
            # FastAPI >= 0.139 registers included routers lazily; descend into
            # the original router instead of expecting flattened APIRoutes.
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                context = getattr(route, "include_context", None)
                _collect(
                    original_router.routes,
                    prefix + str(getattr(context, "prefix", "") or ""),
                )
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None or methods is None:
                continue
            for method in methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                key = (prefix + path, method)
                counts[key] = counts.get(key, 0) + 1

    _collect(main.app.routes, "")

    assert counts[("/api/system/info", "GET")] == 1
    assert counts[("/api/self-host/migration/contract", "GET")] == 1


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_attaches_request_id_header() -> None:
    from app import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert "x-request-id" in {k.lower() for k in response.headers.keys()}


@pytest.mark.asyncio
async def test_middleware_echoes_provided_request_id() -> None:
    from app import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/", headers={"X-Request-ID": "my-id-123"})

    assert response.headers.get("X-Request-ID") == "my-id-123"
