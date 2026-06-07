"""DB tests: MCP-synced items become linked graph citizens (entities+mentions)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.mcp_client import McpIntrospection, McpTool
from app.core.mcp_ingest import sync_connection
from app.models.entity import Entity, EntityMention
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


async def _make_connection(db, user) -> McpConnection:
    conn = McpConnection(
        user_id=user.id,
        server_label="Mail",
        server_url=f"https://mcp.example.com/{uuid4().hex}",
        auth_type="none",
        privacy_level="internal",
        enabled=True,
    )
    db.add(conn)
    await db.flush()
    return conn


class GmailLikeClient:
    """search_threads -> get_thread(threadId) -> messages[] (Gmail recipe)."""

    def __init__(self, threads: dict[str, list[dict]]):
        # threads: {thread_id: [message dicts]}
        self._threads = threads

    async def list_resources(self):
        return []

    async def introspect(self):
        specs = [
            McpTool("search_threads", input_schema={"properties": {"query": {}, "pageToken": {}}}),
            McpTool(
                "get_thread",
                input_schema={"properties": {"threadId": {}}, "required": ["threadId"]},
            ),
        ]
        return McpIntrospection(tools=[s.name for s in specs], resources=[], tool_specs=specs)

    async def call_tool(self, name, args):
        import json

        if name == "search_threads":
            return json.dumps({"threads": [{"id": tid} for tid in self._threads]})
        if name == "get_thread":
            msgs = self._threads.get(args["threadId"], [])
            return json.dumps({"messages": msgs})
        return "{}"


def _msg(mid, frm, subject, to=None, body="hello"):
    m = {"id": mid, "from": frm, "subject": subject, "plaintext_body": body,
         "internalDate": "1700000000000"}
    if to:
        m["to"] = to
    return m


async def test_email_sync_creates_people_topics_and_mentions(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    threads = {
        "t1": [_msg("m1", "Alice <alice@x.com>", "Re: Q3 launch", to="Bob <bob@y.com>")],
    }
    result = await sync_connection(
        db_session, conn,
        client_factory=lambda url, token: GmailLikeClient(threads),
        embedder=_embedder,
    )
    assert result.status == "succeeded"
    assert result.created == 1

    entities = (
        await db_session.execute(select(Entity).where(Entity.user_id == user.id))
    ).scalars().all()
    people = {e.name: e for e in entities if e.type == "person"}
    topics = {e.name for e in entities if e.type == "topic"}
    assert "Alice" in people and "Bob" in people
    assert "Q3 launch" in topics  # thread-clustering topic, Re: stripped
    # Alice carries her email as a strong identity key.
    assert "alice@x.com" in (people["Alice"].metadata_ or {}).get("identity_keys", [])

    item = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalar_one()
    mentions = (
        await db_session.execute(
            select(EntityMention).where(
                EntityMention.source_kind == "item", EntityMention.source_id == item.id
            )
        )
    ).scalars().all()
    assert len(mentions) >= 3  # Alice, Bob, topic

    run = (
        await db_session.execute(
            select(McpIngestionRun).where(McpIngestionRun.connection_id == conn.id)
        )
    ).scalar_one()
    assert run.mentions_recorded >= 3
    assert run.extract_errors == 0


async def test_same_email_address_resolves_to_one_person(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    # Same address, two different display names, across two threads.
    threads = {
        "t1": [_msg("m1", "Alice <alice@x.com>", "First")],
        "t2": [_msg("m2", "Alice Smith <alice@x.com>", "Second")],
    }
    await sync_connection(
        db_session, conn,
        client_factory=lambda url, token: GmailLikeClient(threads),
        embedder=_embedder,
    )
    alice_entities = (
        await db_session.execute(
            select(Entity).where(Entity.user_id == user.id, Entity.type == "person")
        )
    ).scalars().all()
    # Identity-keyed dedup: one person for alice@x.com despite two display names.
    matching = [
        e for e in alice_entities
        if "alice@x.com" in (e.metadata_ or {}).get("identity_keys", [])
    ]
    assert len(matching) == 1
    # That one person is mentioned by both items.
    mentions = (
        await db_session.execute(
            select(EntityMention).where(EntityMention.entity_id == matching[0].id)
        )
    ).scalars().all()
    assert len(mentions) == 2


async def test_automated_sender_not_minted_but_item_kept(db_session):
    user = await _make_user(db_session)
    conn = await _make_connection(db_session, user)
    threads = {"t1": [_msg("m1", "noreply@service.com", "Your invoice")]}
    await sync_connection(
        db_session, conn,
        client_factory=lambda url, token: GmailLikeClient(threads),
        embedder=_embedder,
    )
    people = (
        await db_session.execute(
            select(Entity).where(Entity.user_id == user.id, Entity.type == "person")
        )
    ).scalars().all()
    assert people == []  # no person for noreply@
    # But the email itself is ingested + searchable.
    items = (await db_session.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    assert len(items) == 1
