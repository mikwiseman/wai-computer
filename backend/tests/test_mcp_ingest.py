"""DB-backed tests for the connect-any-MCP ingestion orchestrator (fake client)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.mcp_client import McpResource
from app.core.mcp_ingest import sync_connection
from app.core.secrets_crypto import encrypt_secret
from app.models.item import Item
from app.models.mcp_connection import McpConnection, McpIngestionRun
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


async def _make_user(db) -> User:
    user = User(email=f"mcp-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _make_connection(db, user, **kw) -> McpConnection:
    conn = McpConnection(
        user_id=user.id,
        server_label=kw.get("label", "My Notes"),
        server_url=kw.get("url", f"https://mcp.example.com/{uuid4().hex}"),
        auth_type=kw.get("auth_type", "none"),
        auth_secret_encrypted=kw.get("secret"),
        privacy_level="internal",
        enabled=True,
    )
    db.add(conn)
    await db.flush()
    return conn


class FakeClient:
    def __init__(self, resources, bodies):
        self._resources = resources
        self._bodies = bodies
        self.token_seen = None

    async def list_resources(self):
        return self._resources

    async def read_resource(self, uri):
        return self._bodies[uri]


async def test_sync_pulls_resources_into_items(db_session) -> None:
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    resources = [
        McpResource(uri="note://1", name="Note One"),
        McpResource(uri="note://2", name="Note Two"),
    ]
    bodies = {"note://1": "first note body", "note://2": "second note body"}

    result = await sync_connection(
        db_session, conn,
        client_factory=lambda url, token: FakeClient(resources, bodies),
        embedder=_embedder,
    )
    assert result.status == "succeeded"
    assert result.seen == 2
    assert result.created == 2

    items = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalars().all()
    assert len(items) == 2
    assert all(i.source == f"mcp:{conn.id}" for i in items)
    assert all(i.kind == "mcp_resource" for i in items)
    assert all(i.authority_score == 0.8 for i in items)
    # A run was recorded.
    runs = (
        await db_session.execute(
            select(McpIngestionRun).where(McpIngestionRun.connection_id == conn.id)
        )
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert runs[0].items_created == 2
    # Cursor advanced.
    assert conn.sync_cursor is not None
    assert conn.last_sync_at is not None


async def test_sync_is_idempotent_across_runs(db_session) -> None:
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    resources = [McpResource(uri="note://1", name="N1")]
    bodies = {"note://1": "stable body"}
    factory = lambda url, token: FakeClient(resources, bodies)  # noqa: E731

    r1 = await sync_connection(db_session, conn, client_factory=factory, embedder=_embedder)
    r2 = await sync_connection(db_session, conn, client_factory=factory, embedder=_embedder)
    assert r1.created == 1
    assert r2.created == 0  # same resource -> deduped on second sync
    items = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalars().all()
    assert len(items) == 1


async def test_sync_redacts_secrets_and_marks_privacy(db_session) -> None:
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    resources = [McpResource(uri="note://secret", name="Creds")]
    bodies = {"note://secret": "deploy key sk-abcdefghijklmnopqrstuvwxyz123456 do not share"}

    await sync_connection(
        db_session, conn,
        client_factory=lambda url, token: FakeClient(resources, bodies),
        embedder=_embedder,
    )
    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert "sk-abcdefghij" not in (item.body or "")
    assert "[REDACTED:openai_key]" in (item.body or "")
    assert item.privacy_level == "secret"


async def test_sync_uses_decrypted_token(db_session) -> None:
    user = await _make_user(db_session)
    conn = await _make_connection(
        db_session, user, auth_type="pat", secret=encrypt_secret("pat-XYZ")
    )
    seen_tokens = {}

    def factory(url, token):
        seen_tokens["token"] = token
        return FakeClient([McpResource(uri="n://1", name="n")], {"n://1": "body"})

    await sync_connection(db_session, conn, client_factory=factory, embedder=_embedder)
    assert seen_tokens["token"] == "pat-XYZ"  # decrypted before use


async def test_sync_failure_marks_run_and_connection(db_session) -> None:
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)

    class BoomClient:
        async def list_resources(self):
            raise RuntimeError("server exploded")

    with pytest.raises(RuntimeError):
        await sync_connection(
            db_session, conn, client_factory=lambda url, token: BoomClient(),
            embedder=_embedder,
        )
    run = (
        await db_session.execute(
            select(McpIngestionRun).where(McpIngestionRun.connection_id == conn.id)
        )
    ).scalar_one()
    assert run.status == "failed"
    assert run.error_code == "RuntimeError"
    assert conn.status == "error"
    assert conn.last_error == "RuntimeError"


async def test_sync_skips_unreadable_resource_but_continues(db_session) -> None:
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    resources = [McpResource(uri="ok://1", name="ok"), McpResource(uri="bad://2", name="bad")]

    class PartialClient:
        async def list_resources(self):
            return resources

        async def read_resource(self, uri):
            if uri == "bad://2":
                raise ValueError("unreadable")
            return "good body"

    result = await sync_connection(
        db_session, conn, client_factory=lambda url, token: PartialClient(),
        embedder=_embedder,
    )
    assert result.status == "succeeded"
    assert result.seen == 2
    assert result.created == 1
    assert result.skipped == 1
