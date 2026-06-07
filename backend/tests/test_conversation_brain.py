"""Wai chats become first-class Brain sources: auto-link, search, backfill.

These lock the fix for "chats are not linked automatically and the button does
nothing": a conversation now seeds graph mentions (source_kind="chat") + builds
searchable chunks, debounced by a watermark, with a bounded sweep for the
legacy backlog.
"""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.conversation_brain import (
    _bucket_entities,
    count_unlinked_conversations,
    link_conversation_to_brain,
    link_unlinked_conversations,
)
from app.core.summarizer import EntityResult
from app.models.companion import ChatMessage, Conversation, ConversationChunk
from app.models.entity import Entity, EntityMention
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.03] * 1536 for _ in texts]


def _entities(*pairs):
    return [EntityResult(name=n, type=t, context="", relations=[]) for n, t in pairs]


async def _default_extractor(_text):
    return _entities(("Alice", "person"), ("Apollo", "project"), ("budget", "topic"))


async def _make_user(db) -> User:
    user = User(email=f"convbrain-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _make_conversation(
    db, user, *, n_pairs=1, title="Planning Apollo", body="Apollo budget"
) -> Conversation:
    conv = Conversation(user_id=user.id, title=title)
    db.add(conv)
    await db.flush()
    for i in range(n_pairs):
        db.add(
            ChatMessage(
                conversation_id=conv.id,
                role="user",
                content=[{"type": "text", "text": f"Let's discuss the {body} {i}"}],
                status="complete",
            )
        )
        db.add(
            ChatMessage(
                conversation_id=conv.id,
                role="assistant",
                content=[{"type": "text", "text": f"Alice owns the {body} {i}"}],
                status="complete",
            )
        )
    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    return conv


# --- _bucket_entities -------------------------------------------------------


def test_bucket_entities_maps_types_and_drops_blanks() -> None:
    people, projects, topics = _bucket_entities(
        _entities(
            ("Alice", "person"),
            ("Acme", "organization"),
            ("Apollo", "project"),
            ("budget", "topic"),
            ("", "person"),
            ("   ", "topic"),
        )
    )
    assert people == ["Alice"]
    assert projects == ["Apollo"]
    assert set(topics) == {"Acme", "budget"}


# --- link_conversation_to_brain --------------------------------------------


async def test_link_conversation_creates_mentions_and_chunks(db_session) -> None:
    user = await _make_user(db_session)
    conv = await _make_conversation(db_session, user, n_pairs=2)

    result = await link_conversation_to_brain(
        db_session,
        user.id,
        conv.id,
        entity_extractor=_default_extractor,
        embedder=_embedder,
    )

    assert result.linked
    assert result.message_count == 4
    assert result.mentions_recorded == 3
    assert result.chunks_written >= 1
    assert result.llm_requests == 1

    mentions = (
        await db_session.execute(
            select(EntityMention).where(
                EntityMention.source_kind == "chat",
                EntityMention.source_id == conv.id,
            )
        )
    ).scalars().all()
    assert len(mentions) == 3

    ents = (
        await db_session.execute(select(Entity).where(Entity.user_id == user.id))
    ).scalars().all()
    by_type: dict[str, list[str]] = {}
    for e in ents:
        by_type.setdefault(e.type, []).append(e.name)
    assert "person" in by_type and "project" in by_type and "topic" in by_type

    await db_session.refresh(conv)
    assert conv.brain_linked_message_count == 4

    chunks = (
        await db_session.execute(
            select(ConversationChunk).where(
                ConversationChunk.conversation_id == conv.id
            )
        )
    ).scalars().all()
    assert len(chunks) == result.chunks_written
    assert all(c.embedding is not None for c in chunks)


async def test_link_conversation_debounces_when_unchanged(db_session) -> None:
    user = await _make_user(db_session)
    conv = await _make_conversation(db_session, user, n_pairs=1)
    calls = {"n": 0}

    async def counting_extractor(_text):
        calls["n"] += 1
        return _entities(("Bob", "person"))

    r1 = await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=counting_extractor, embedder=_embedder
    )
    assert r1.linked
    r2 = await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=counting_extractor, embedder=_embedder
    )
    assert not r2.linked
    assert r2.skipped_reason == "unchanged"
    assert calls["n"] == 1  # extractor not called a second time


async def test_link_conversation_relinks_when_messages_grow(db_session) -> None:
    user = await _make_user(db_session)
    conv = await _make_conversation(db_session, user, n_pairs=1)
    await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=_default_extractor, embedder=_embedder
    )
    # Two more complete messages arrive.
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="user",
            content=[{"type": "text", "text": "also loop in Carol"}],
            status="complete",
        )
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=[{"type": "text", "text": "noted, Carol joins"}],
            status="complete",
        )
    )
    await db_session.flush()

    async def carol_extractor(_text):
        return _entities(("Carol", "person"))

    r = await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=carol_extractor, embedder=_embedder
    )
    assert r.linked
    assert r.message_count == 4


async def test_link_conversation_too_short(db_session) -> None:
    user = await _make_user(db_session)
    conv = Conversation(user_id=user.id, title="hi")
    db_session.add(conv)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="user",
            content=[{"type": "text", "text": "hi"}],
            status="complete",
        )
    )
    await db_session.flush()

    r = await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=_default_extractor, embedder=_embedder
    )
    assert not r.linked
    assert r.skipped_reason == "too_short"


async def test_link_conversation_force_relinks(db_session) -> None:
    user = await _make_user(db_session)
    conv = await _make_conversation(db_session, user, n_pairs=1)
    calls = {"n": 0}

    async def counting_extractor(_text):
        calls["n"] += 1
        return _entities(("Bob", "person"))

    await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=counting_extractor, embedder=_embedder
    )
    r2 = await link_conversation_to_brain(
        db_session,
        user.id,
        conv.id,
        entity_extractor=counting_extractor,
        embedder=_embedder,
        force=True,
    )
    assert r2.linked
    assert calls["n"] == 2


async def test_link_conversation_ignores_streaming_messages(db_session) -> None:
    """An in-flight (streaming) assistant turn must not count toward linking."""
    user = await _make_user(db_session)
    conv = Conversation(user_id=user.id, title="live")
    db_session.add(conv)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="user",
            content=[{"type": "text", "text": "tell me about Apollo"}],
            status="complete",
        )
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=[{"type": "text", "text": "thinking..."}],
            status="streaming",
        )
    )
    await db_session.flush()

    r = await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=_default_extractor, embedder=_embedder
    )
    # Only one complete message -> too short.
    assert not r.linked
    assert r.skipped_reason == "too_short"


# --- searchable / Ask-able --------------------------------------------------


async def test_linked_chat_is_searchable(db_session) -> None:
    user = await _make_user(db_session)
    conv = await _make_conversation(
        db_session, user, n_pairs=1, title="Apollo budget", body="Apollo budget"
    )
    await link_conversation_to_brain(
        db_session, user.id, conv.id, entity_extractor=_default_extractor, embedder=_embedder
    )

    from app.core.unified_search import unified_search

    with patch(
        "app.core.unified_search.generate_embedding", return_value=[0.03] * 1536
    ):
        hits = await unified_search(db_session, user.id, "Apollo budget", limit=10)

    assert any(
        h.source_kind == "chat" and h.parent_id == str(conv.id) for h in hits
    )


# --- link_unlinked_conversations (the "Link" button + nightly sweep) --------


async def test_link_unlinked_conversations_links_and_bounds(db_session) -> None:
    user = await _make_user(db_session)
    for i in range(3):
        await _make_conversation(db_session, user, n_pairs=1, title=f"c{i}")

    assert await count_unlinked_conversations(db_session, user.id) == 3

    res = await link_unlinked_conversations(
        db_session, user.id, limit=2, entity_extractor=_default_extractor, embedder=_embedder
    )
    assert res.conversations_scanned == 2
    assert res.conversations_linked == 2
    assert res.mentions_recorded == 6  # 3 per conversation
    assert await count_unlinked_conversations(db_session, user.id) == 1


async def test_link_unlinked_conversations_isolates_one_failure(db_session) -> None:
    user = await _make_user(db_session)
    await _make_conversation(db_session, user, n_pairs=1, title="good", body="good budget")
    await _make_conversation(db_session, user, n_pairs=1, title="bad", body="EXPLODE here")

    async def flaky_extractor(text):
        if "EXPLODE" in text:
            raise RuntimeError("boom")
        return _entities(("Alice", "person"))

    res = await link_unlinked_conversations(
        db_session, user.id, limit=10, entity_extractor=flaky_extractor, embedder=_embedder
    )
    assert res.conversations_scanned == 2
    assert res.conversations_linked == 1  # the bad one is isolated, good persists
    # The good conversation's mention survived the other's rollback.
    mentions = (
        await db_session.execute(
            select(EntityMention).where(
                EntityMention.user_id == user.id,
                EntityMention.source_kind == "chat",
            )
        )
    ).scalars().all()
    assert len(mentions) == 1


# --- /brain/sync route ------------------------------------------------------


async def test_brain_sync_route_links_chats_when_requested(
    client, auth_headers, db_session
) -> None:
    user = (
        await db_session.execute(select(User).order_by(User.created_at.desc()))
    ).scalars().first()
    conv = await _make_conversation(db_session, user, n_pairs=1, title="Apollo")

    with (
        patch("app.core.conversation_brain.extract_entities", _default_extractor),
        patch("app.core.conversation_brain.generate_embeddings", _embedder),
    ):
        resp = await client.post(
            "/api/brain/sync",
            json={"limit": 100, "include_chats": True},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["conversations_linked"] >= 1
    assert data["llm_requests"] >= 1

    await db_session.refresh(conv)
    assert conv.brain_linked_message_count == 2


async def test_brain_sync_route_skips_chats_by_default(
    client, auth_headers, db_session
) -> None:
    """The auto-sync on Brain open must not spend tokens on chats."""
    user = (
        await db_session.execute(select(User).order_by(User.created_at.desc()))
    ).scalars().first()
    conv = await _make_conversation(db_session, user, n_pairs=1, title="Apollo")

    resp = await client.post(
        "/api/brain/sync", json={"limit": 100}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["conversations_scanned"] == 0
    assert data["conversations_linked"] == 0

    await db_session.refresh(conv)
    assert conv.brain_linked_message_count == 0  # untouched
