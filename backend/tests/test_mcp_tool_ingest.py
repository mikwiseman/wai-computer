"""DB-backed tests for the tool-driven MCP ingestion path (fake tool client)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.mcp_client import McpIntrospection, McpTool
from app.core.mcp_ingest import DisallowedToolError, _guarded_call, sync_connection
from app.models.item import Item
from app.models.mcp_connection import McpConnection
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


def _tool(name, props=None, required=None) -> McpTool:
    schema = None
    if props or required:
        schema = {"properties": props or {}, "required": required or []}
    return McpTool(name, input_schema=schema)


async def _make_user(db) -> User:
    user = User(email=f"mcp-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _make_connection(db, user) -> McpConnection:
    conn = McpConnection(
        user_id=user.id,
        server_label="Src",
        server_url=f"https://mcp.example.com/{uuid4().hex}",
        auth_type="none",
        privacy_level="internal",
        enabled=True,
    )
    db.add(conn)
    await db.flush()
    return conn


class FakeToolClient:
    """A tool-based MCP server: no resources, data behind tools."""

    def __init__(self, specs: list[McpTool], responses: dict):
        self._specs = specs
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def list_resources(self):
        return []

    async def introspect(self):
        return McpIntrospection(
            tools=[t.name for t in self._specs], resources=[], tool_specs=self._specs
        )

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        resp = self._responses.get(name)
        if resp is None:
            return "{}"
        return resp(args) if callable(resp) else resp


# ── recipe path: Telegram (scope fan-out, no fetch) ─────────────────────────
async def test_telegram_recipe_fans_out_over_chats(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    specs = [
        McpTool("list_chats"),
        _tool("get_chat_messages", props={"chat_id": {}, "before": {}}, required=["chat_id"]),
        McpTool("send_message"),  # mutation: must never be called
        McpTool("search_messages"),
    ]

    def messages(args):
        cid = args["chat_id"]
        return (
            '{"messages":[{"message_id":%d,"text":"hi from %d",'
            '"date":"2026-06-01T00:00:00Z"}]}' % (cid * 10, cid)
        )

    responses = {
        "list_chats": '{"chats":[{"chat_id":1,"title":"A"},{"chat_id":2,"title":"B"}]}',
        "get_chat_messages": messages,
    }
    client = FakeToolClient(specs, responses)

    result = await sync_connection(
        db_session, conn, client_factory=lambda url, token: client, embedder=_embedder
    )
    assert result.status == "succeeded"
    assert result.created == 2  # one message per chat
    items = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    assert len(items) == 2
    assert all(i.kind == "message" for i in items)
    assert all(i.source == f"mcp:{conn.id}" for i in items)
    assert all(i.metadata_ is not None for i in items)  # raw record kept for linking
    # The mutation tool was never called (read-only safety).
    assert not any(name == "send_message" for name, _ in client.calls)


# ── recipe path: Gmail-style enumerate -> fetch ─────────────────────────────
async def test_gmail_recipe_enumerate_then_fetch(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    specs = [
        _tool("search_threads", props={"query": {}, "pageToken": {}}),
        _tool("get_thread", props={"threadId": {}}, required=["threadId"]),
    ]

    def thread(args):
        tid = args["threadId"]
        return (
            '{"messages":[{"id":"%s-m","subject":"Subj %s","plaintext_body":"Body",'
            '"internalDate":"1700000000000"}]}' % (tid, tid)
        )

    responses = {
        "search_threads": '{"threads":[{"id":"t1"},{"id":"t2"}]}',
        "get_thread": thread,
    }
    client = FakeToolClient(specs, responses)
    result = await sync_connection(
        db_session, conn, client_factory=lambda url, token: client, embedder=_embedder
    )
    assert result.status == "succeeded"
    assert result.created == 2
    items = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    assert {i.kind for i in items} == {"email"}
    assert any(name == "get_thread" for name, _ in client.calls)


# ── heuristic path: unknown server ──────────────────────────────────────────
async def test_heuristic_unknown_server(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    specs = [
        _tool("search_widgets", props={"query": {}, "cursor": {}}),
        _tool("get_widget", props={"id": {}}, required=["id"]),
    ]
    responses = {
        "search_widgets": '{"results":[{"id":"w1"},{"id":"w2"}]}',
        "get_widget": lambda a: '{"id":"%s","title":"W","content":"body"}' % a["id"],
    }
    client = FakeToolClient(specs, responses)
    result = await sync_connection(
        db_session, conn, client_factory=lambda url, token: client, embedder=_embedder
    )
    assert result.status == "succeeded"
    assert result.created == 2
    items = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    assert all(i.kind == "mcp_item" for i in items)


# ── needs_setup: a server we can't read ─────────────────────────────────────
async def test_needs_setup_when_no_enumerate(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    specs = [
        _tool("get_thread", props={"threadId": {}}, required=["threadId"]),
        McpTool("me"),
    ]
    client = FakeToolClient(specs, {})
    result = await sync_connection(
        db_session, conn, client_factory=lambda url, token: client, embedder=_embedder
    )
    assert result.status == "needs_setup"
    assert conn.status == "needs_setup"
    assert result.created == 0


# ── idempotency across runs ─────────────────────────────────────────────────
async def test_tool_sync_idempotent(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    specs = [
        McpTool("list_chats"),
        _tool("get_chat_messages", props={"chat_id": {}}, required=["chat_id"]),
    ]
    responses = {
        "list_chats": '{"chats":[{"chat_id":5,"title":"C"}]}',
        "get_chat_messages": (
            '{"messages":[{"message_id":99,"text":"stable",'
            '"date":"2026-06-01T00:00:00Z"}]}'
        ),
    }
    factory = lambda url, token: FakeToolClient(specs, responses)  # noqa: E731
    r1 = await sync_connection(db_session, conn, client_factory=factory, embedder=_embedder)
    r2 = await sync_connection(db_session, conn, client_factory=factory, embedder=_embedder)
    assert r1.created == 1
    assert r2.created == 0  # deduped
    items = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    assert len(items) == 1


# ── read-only guard ─────────────────────────────────────────────────────────
async def test_guarded_call_blocks_mutation_and_unlisted():
    call = _guarded_call({"search_threads", "send_message"})

    class C:
        async def call_tool(self, name, args):
            return "{}"

    c = C()
    # In allow-list but a mutation name -> blocked.
    with pytest.raises(DisallowedToolError):
        await call(c, "send_message", {})
    # Not in allow-list -> blocked.
    with pytest.raises(DisallowedToolError):
        await call(c, "delete_thread", {})
    # Allowed read tool -> ok.
    assert await call(c, "search_threads", {}) == "{}"
