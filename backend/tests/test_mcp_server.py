"""Tests for app.mcp_server — the FastMCP app construction and tool handlers."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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

    instructions = captured["instructions"]
    for tool_name in (
        "search",
        "fetch",
        "list_folders",
        "list_recordings",
        "list_action_items",
    ):
        assert tool_name in instructions, f"{tool_name} missing from instructions"
    assert captured["name"] == "WaiComputer"
    assert captured["streamable_http_path"] == "/mcp"
    assert captured["stateless_http"] is True
    assert captured["json_response"] is True


def test_create_mcp_app_registers_all_tools() -> None:
    """Sanity check that every advertised tool is wired into FastMCP."""
    import asyncio

    settings = get_settings()
    captured_mcp: dict[str, object] = {}
    original_init = mcp_server.FastMCP.__init__

    def _capturing_init(self, *args, **kwargs):  # noqa: ANN001
        original_init(self, *args, **kwargs)
        captured_mcp["mcp"] = self

    with patch.object(mcp_server.FastMCP, "__init__", _capturing_init):
        _ = mcp_server.create_mcp_app(settings)

    tools = asyncio.run(captured_mcp["mcp"].list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "search",
        "fetch",
        "list_folders",
        "list_recordings",
        "list_action_items",
    }


@pytest.mark.asyncio
async def test_create_mcp_app_tool_handlers_use_authenticated_user_and_db(monkeypatch) -> None:
    """Execute the registered handlers against mocked auth/db/tool layers."""

    class FakeFastMCP:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.tools: dict[str, object] = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func

            return decorator

        def streamable_http_app(self):
            return self

    captured: dict[str, FakeFastMCP] = {}

    def fake_fastmcp(**kwargs):
        instance = FakeFastMCP(**kwargs)
        captured["mcp"] = instance
        return instance

    calls: list[tuple] = []

    @asynccontextmanager
    async def fake_db_context():
        yield "db-session"

    async def fake_resolve(token: str):
        assert token == "access-token"
        return "user-123"

    async def fake_search(db, user_id, query, *, limit, folder_ids):
        calls.append(("search", db, user_id, query, limit, folder_ids))
        return {"results": [{"id": "r1", "snippet": "match"}]}

    async def fake_fetch(db, user_id, recording_id):
        calls.append(("fetch", db, user_id, recording_id))
        return {"id": recording_id, "title": "Recording"}

    async def fake_folders(db, user_id):
        calls.append(("folders", db, user_id))
        return {"folders": [{"id": "f1", "name": "Inbox"}]}

    async def fake_recordings(db, user_id, *, folder_ids, limit, cursor):
        calls.append(("recordings", db, user_id, folder_ids, limit, cursor))
        return {"results": [{"id": "r2"}], "next_cursor": None}

    async def fake_actions(db, user_id, *, status, folder_ids, limit, cursor):
        calls.append(("actions", db, user_id, status, folder_ids, limit, cursor))
        return {"results": [{"task": "Follow up"}], "next_cursor": None}

    monkeypatch.setattr(mcp_server, "FastMCP", fake_fastmcp)
    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(token="access-token"),
    )
    monkeypatch.setattr(mcp_server, "resolve_mcp_access_token_user_id", fake_resolve)
    monkeypatch.setattr(mcp_server, "get_db_context", fake_db_context)
    monkeypatch.setattr(mcp_server, "search_recordings_for_mcp", fake_search)
    monkeypatch.setattr(mcp_server, "fetch_recording_for_mcp", fake_fetch)
    monkeypatch.setattr(mcp_server, "list_folders_for_mcp", fake_folders)
    monkeypatch.setattr(mcp_server, "list_recordings_for_mcp", fake_recordings)
    monkeypatch.setattr(mcp_server, "list_action_items_for_mcp", fake_actions)

    settings = SimpleNamespace(
        frontend_url="https://wai.computer",
        mcp_issuer_url_resolved="https://wai.computer",
        mcp_resource_url_resolved="https://api.wai.computer/mcp",
        mcp_client_secret_expire_days=30,
    )
    app = mcp_server.create_mcp_app(settings)
    tools = app.tools

    search = json.loads(await tools["search"]("roadmap", limit=5, folder_ids=["f1"]))
    fetch = json.loads(await tools["fetch"]("r1"))
    folders = json.loads(await tools["list_folders"]())
    recordings = json.loads(await tools["list_recordings"](folder_ids=["f1"], limit=3, cursor="c1"))
    actions = json.loads(
        await tools["list_action_items"](
            status="pending",
            folder_ids=["f1"],
            limit=4,
            cursor="c2",
        )
    )

    assert search["results"][0]["snippet"] == "match"
    assert fetch["title"] == "Recording"
    assert folders["folders"][0]["name"] == "Inbox"
    assert recordings["results"][0]["id"] == "r2"
    assert actions["results"][0]["task"] == "Follow up"
    assert calls == [
        ("search", "db-session", "user-123", "roadmap", 5, ["f1"]),
        ("fetch", "db-session", "user-123", "r1"),
        ("folders", "db-session", "user-123"),
        ("recordings", "db-session", "user-123", ["f1"], 3, "c1"),
        ("actions", "db-session", "user-123", "pending", ["f1"], 4, "c2"),
    ]
    assert captured["mcp"].kwargs["transport_security"].allowed_hosts == [
        "127.0.0.1",
        "api.wai.computer",
        "localhost",
        "wai.computer",
    ]


@pytest.mark.asyncio
async def test_mcp_tool_handlers_reject_missing_or_invalid_access_token(monkeypatch) -> None:
    class FakeFastMCP:
        def __init__(self, **kwargs):
            self.tools: dict[str, object] = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func

            return decorator

        def streamable_http_app(self):
            return self

    monkeypatch.setattr(mcp_server, "FastMCP", lambda **kwargs: FakeFastMCP(**kwargs))
    settings = SimpleNamespace(
        frontend_url="https://wai.computer",
        mcp_issuer_url_resolved="https://wai.computer",
        mcp_resource_url_resolved="https://api.wai.computer/mcp",
        mcp_client_secret_expire_days=30,
    )

    monkeypatch.setattr(mcp_server, "get_access_token", lambda: None)
    app = mcp_server.create_mcp_app(settings)
    with pytest.raises(ValueError, match="MCP access token is required"):
        await app.tools["list_folders"]()

    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(token="bad-token"),
    )

    async def invalid_token(_token: str):
        return None

    monkeypatch.setattr(mcp_server, "resolve_mcp_access_token_user_id", invalid_token)
    app = mcp_server.create_mcp_app(settings)
    with pytest.raises(ValueError, match="MCP access token is invalid"):
        await app.tools["list_folders"]()


@pytest.mark.asyncio
async def test_mcp_fetch_tool_rejects_missing_recording(monkeypatch) -> None:
    class FakeFastMCP:
        def __init__(self, **kwargs):
            self.tools: dict[str, object] = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func

            return decorator

        def streamable_http_app(self):
            return self

    @asynccontextmanager
    async def fake_db_context():
        yield "db-session"

    async def fake_resolve(_token: str):
        return "user-123"

    async def missing_fetch(_db, _user_id, _recording_id):
        return None

    monkeypatch.setattr(mcp_server, "FastMCP", lambda **kwargs: FakeFastMCP(**kwargs))
    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(token="access-token"),
    )
    monkeypatch.setattr(mcp_server, "resolve_mcp_access_token_user_id", fake_resolve)
    monkeypatch.setattr(mcp_server, "get_db_context", fake_db_context)
    monkeypatch.setattr(mcp_server, "fetch_recording_for_mcp", missing_fetch)

    settings = SimpleNamespace(
        frontend_url="https://wai.computer",
        mcp_issuer_url_resolved="https://wai.computer",
        mcp_resource_url_resolved="https://api.wai.computer/mcp",
        mcp_client_secret_expire_days=30,
    )
    app = mcp_server.create_mcp_app(settings)

    with pytest.raises(ValueError, match="Recording not found"):
        await app.tools["fetch"]("missing")
