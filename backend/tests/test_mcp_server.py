"""Tests for app.mcp_server — the FastMCP app construction and tool handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app import mcp_server
from app.config import get_settings

# ---------------------------------------------------------------------------
# _allowed_hosts
# ---------------------------------------------------------------------------


def test_allowed_hosts_always_includes_loopback() -> None:
    settings = SimpleNamespace(
        frontend_url="https://example.test",
        mcp_issuer_url_resolved="https://example.test",
        mcp_resource_url_resolved="https://example.test",
    )
    hosts = mcp_server._allowed_hosts(settings)
    assert "localhost" in hosts
    assert "127.0.0.1" in hosts
    assert "example.test" in hosts


def test_allowed_hosts_collects_distinct_netlocs() -> None:
    settings = SimpleNamespace(
        frontend_url="https://wai.computer",
        mcp_issuer_url_resolved="https://wai.computer/mcp",
        mcp_resource_url_resolved="https://api.wai.computer/mcp",
    )
    hosts = mcp_server._allowed_hosts(settings)
    assert "wai.computer" in hosts
    assert "api.wai.computer" in hosts
    # localhost always present
    assert {"localhost", "127.0.0.1"}.issubset(set(hosts))
    # No duplicates
    assert len(hosts) == len(set(hosts))


def test_allowed_hosts_skips_empty_netlocs() -> None:
    settings = SimpleNamespace(
        frontend_url="",  # urlparse("").netloc == "" → skipped
        mcp_issuer_url_resolved="https://wai.computer",
        mcp_resource_url_resolved="not a url",
    )
    hosts = mcp_server._allowed_hosts(settings)
    # `"not a url"` has empty netloc — should be skipped without error
    assert "" not in hosts
    assert "wai.computer" in hosts


def test_allowed_hosts_returns_sorted_list() -> None:
    settings = SimpleNamespace(
        frontend_url="https://zzz.test",
        mcp_issuer_url_resolved="https://aaa.test",
        mcp_resource_url_resolved="https://mmm.test",
    )
    hosts = mcp_server._allowed_hosts(settings)
    assert hosts == sorted(hosts)


# ---------------------------------------------------------------------------
# create_mcp_app
# ---------------------------------------------------------------------------


def test_create_mcp_app_returns_starlette_app() -> None:
    settings = get_settings()
    app = mcp_server.create_mcp_app(settings)
    # Starlette duck-type
    assert hasattr(app, "router") or hasattr(app, "routes")
    assert callable(app)


def test_create_mcp_app_instructions_mention_tools() -> None:
    """The instructions string is part of the user-facing contract — it's what
    the MCP client first sees. Changes to it would break documentation."""
    settings = get_settings()
    captured: dict[str, object] = {}
    original_init = mcp_server.FastMCP.__init__

    def _capturing_init(self, *args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return original_init(self, *args, **kwargs)

    with patch.object(mcp_server.FastMCP, "__init__", _capturing_init):
        _ = mcp_server.create_mcp_app(settings)

    assert "search" in captured["instructions"]
    assert "fetch" in captured["instructions"]
    assert captured["name"] == "WaiComputer"
    assert captured["streamable_http_path"] == "/mcp"
    assert captured["stateless_http"] is True
    assert captured["json_response"] is True
