"""Direct tests for the conversation-linking Celery task wrappers.

The task bodies only run via the broker in production, so cover the success +
swallowed-error + sweep paths here. Mirrors test_second_brain_task_wrappers:
swap the inner async fn for a coroutine factory so asyncio.run consumes a real
awaitable while DB work is stubbed.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.companion import ChatMessage, Conversation
from app.models.entity import EntityMention
from app.models.user import User
from app.tasks import conversation_linking


def _coro_factory(*, raises: Exception | None = None, returns=None):
    async def _inner(*args, **kwargs):
        if raises is not None:
            raise raises
        return returns

    return _inner


def _ctx_yielding(session):
    """Drop-in for get_db_context that always yields the test session."""

    @asynccontextmanager
    async def _cm():
        yield session

    return _cm


async def _embedder(texts):
    return [[0.04] * 1536 for _ in texts]


async def _extractor(_text):
    from app.core.summarizer import EntityResult

    return [EntityResult(name="Alice", type="person", context="", relations=[])]


async def _seed_chat(db, user):
    conv = Conversation(user_id=user.id, title="Apollo")
    db.add(conv)
    await db.flush()
    db.add(
        ChatMessage(
            conversation_id=conv.id,
            role="user",
            content=[{"type": "text", "text": "Alice owns Apollo"}],
            status="complete",
        )
    )
    db.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=[{"type": "text", "text": "Yes, Alice leads it"}],
            status="complete",
        )
    )
    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    return conv


def test_link_conversation_task_success() -> None:
    with patch.object(conversation_linking, "_link_conversation", _coro_factory()):
        conversation_linking.link_conversation("conv-1", "user-1")


def test_link_conversation_task_swallows_errors() -> None:
    """A broker-run link failure must never crash the worker — the nightly
    sweep is the backstop, so the task logs and returns instead of raising."""
    with patch.object(
        conversation_linking,
        "_link_conversation",
        _coro_factory(raises=RuntimeError("boom")),
    ):
        # Must NOT raise.
        conversation_linking.link_conversation("conv-1", "user-1")


def test_sweep_unlinked_conversations_task_returns_totals() -> None:
    totals = {"users_processed": 2, "conversations_linked": 5}
    with patch.object(
        conversation_linking,
        "_sweep_unlinked_conversations",
        _coro_factory(returns=totals),
    ):
        assert conversation_linking.sweep_unlinked_conversations(limit_per_user=10) == totals


@pytest.mark.asyncio
async def test_link_conversation_inner_links_against_db(db_session) -> None:
    user = User(email=f"clt-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv = await _seed_chat(db_session, user)

    with (
        patch.object(conversation_linking, "get_db_context", _ctx_yielding(db_session)),
        patch("app.core.conversation_brain.extract_entities", _extractor),
        patch("app.core.conversation_brain.generate_embeddings", _embedder),
    ):
        await conversation_linking._link_conversation(str(conv.id), str(user.id))

    mentions = (
        await db_session.execute(
            select(EntityMention).where(
                EntityMention.source_kind == "chat", EntityMention.source_id == conv.id
            )
        )
    ).scalars().all()
    assert len(mentions) == 1


@pytest.mark.asyncio
async def test_sweep_inner_links_unlinked(db_session) -> None:
    user = User(email=f"clt-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_chat(db_session, user)
    await _seed_chat(db_session, user)

    with (
        patch.object(conversation_linking, "get_db_context", _ctx_yielding(db_session)),
        patch("app.core.conversation_brain.extract_entities", _extractor),
        patch("app.core.conversation_brain.generate_embeddings", _embedder),
    ):
        totals = await conversation_linking._sweep_unlinked_conversations(25)

    assert totals["users_processed"] == 1
    assert totals["conversations_linked"] == 2
