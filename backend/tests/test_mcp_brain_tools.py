"""Tests for the brain-level MCP tools (ask / search / fetch)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.brain_ask import AnswerCitation, AnswerFreshness, BrainAnswer
from app.core.item_ingest import ingest_item
from app.core.mcp_brain_tools import (
    REMEMBER_MAX_CHARS,
    ask_brain_for_mcp,
    fetch_document_for_mcp,
    remember_for_mcp,
    search_brain_for_mcp,
)
from app.models.companion import ChatMessage, Conversation
from app.models.item import Item
from app.models.recording import Recording, Segment
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _embedder(texts):
    return [[0.01] * 1536 for _ in texts]


async def _make_user(db) -> User:
    user = User(email=f"mcpbrain-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _make_recording(db, user, *, title, content) -> Recording:
    rec = Recording(user_id=user.id, title=title, type="meeting", status="ready")
    db.add(rec)
    await db.flush()
    db.add(
        Segment(
            recording_id=rec.id, content=content, start_ms=0, end_ms=1000, embedding=[0.02] * 1536
        )
    )
    await db.flush()
    return rec


async def _make_chat(db, user, *, title, text) -> Conversation:
    convo = Conversation(user_id=user.id, title=title)
    db.add(convo)
    await db.flush()
    db.add(
        ChatMessage(
            conversation_id=convo.id,
            role="user",
            status="complete",
            content=[{"type": "text", "text": text}],
        )
    )
    await db.flush()
    return convo


async def test_ask_brain_for_mcp_maps_answer_and_citations() -> None:
    answer = BrainAnswer(
        answer="You approved the Q3 budget.",
        citations=[
            AnswerCitation(
                id="chunk-1",
                source_kind="recording",
                source_id="11111111-1111-1111-1111-111111111111",
                title="Budget Meeting",
                start_ms=4200,
            )
        ],
        gaps=["No data after May."],
        freshness=AnswerFreshness(
            newest_source_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            weeks_since=5,
            stale=True,
        ),
    )
    with patch("app.core.mcp_brain_tools.ask_brain", return_value=answer):
        result = await ask_brain_for_mcp(db=None, user_id=uuid4(), question="what about the budget")

    assert result["answer"] == "You approved the Q3 budget."
    assert result["gaps"] == ["No data after May."]
    assert result["freshness"]["stale"] is True
    assert result["freshness"]["weeks_since"] == 5
    assert result["freshness"]["newest_source_at"].startswith("2026-05-01")
    (cite,) = result["citations"]
    assert cite["source_kind"] == "recording"
    assert cite["id"] == "11111111-1111-1111-1111-111111111111"
    assert cite["title"] == "Budget Meeting"
    assert "recording=11111111-1111-1111-1111-111111111111" in cite["url"]


async def test_search_brain_for_mcp_spans_sources(db_session) -> None:
    user = await _make_user(db_session)
    await _make_recording(
        db_session, user, title="Budget Meeting", content="we approved the quarterly budget"
    )
    await ingest_item(
        db_session,
        user.id,
        source="paste",
        kind="note",
        title="Budget Note",
        body="a note about the quarterly budget plan",
        embedder=_embedder,
    )

    with patch("app.core.unified_search.generate_embedding", return_value=[0.02] * 1536):
        result = await search_brain_for_mcp(db_session, user.id, "quarterly budget", limit=10)

    kinds = {r["metadata"]["source_kind"] for r in result["results"]}
    assert {"recording", "item"} <= kinds
    for row in result["results"]:
        assert row["id"]
        assert row["text"]
        assert row["url"].endswith(row["id"])
        assert f"{row['metadata']['source_kind']}=" in row["url"]


async def test_search_brain_for_mcp_empty_query(db_session) -> None:
    user = await _make_user(db_session)
    assert await search_brain_for_mcp(db_session, user.id, "  ", limit=10) == {"results": []}


async def test_fetch_document_polymorphic(db_session) -> None:
    user = await _make_user(db_session)
    rec = await _make_recording(db_session, user, title="Standup", content="we shipped the brain")
    item, _ = await ingest_item(
        db_session,
        user.id,
        source="paste",
        kind="note",
        title="My Note",
        body="remember the launch date is Friday",
        embedder=_embedder,
    )
    chat = await _make_chat(
        db_session, user, title="Planning chat", text="we decided to ship the memory bank"
    )

    rec_doc = await fetch_document_for_mcp(db_session, user.id, rec.id)
    assert rec_doc is not None and rec_doc["metadata"]["source_kind"] == "recording"
    assert "we shipped the brain" in rec_doc["text"]

    item_doc = await fetch_document_for_mcp(db_session, user.id, item.id)
    assert item_doc is not None and item_doc["metadata"]["source_kind"] == "item"
    assert "Friday" in item_doc["text"]
    assert "item=" in item_doc["url"]

    chat_doc = await fetch_document_for_mcp(db_session, user.id, chat.id)
    assert chat_doc is not None and chat_doc["metadata"]["source_kind"] == "chat"
    assert "memory bank" in chat_doc["text"]
    assert "chat=" in chat_doc["url"]


async def test_fetch_document_unknown_and_cross_user(db_session) -> None:
    user = await _make_user(db_session)
    other = await _make_user(db_session)
    rec = await _make_recording(db_session, other, title="Theirs", content="secret content")

    assert await fetch_document_for_mcp(db_session, user.id, rec.id) is None  # cross-user
    assert await fetch_document_for_mcp(db_session, user.id, uuid4()) is None  # unknown
    assert await fetch_document_for_mcp(db_session, user.id, "not-a-uuid") is None  # malformed


async def test_remember_for_mcp_creates_and_dedupes(db_session) -> None:
    user = await _make_user(db_session)

    async def _embed(texts):
        return [[0.01] * 1536 for _ in texts]

    with (
        patch("app.core.item_ingest.generate_embeddings", _embed),
        patch("app.core.mcp_brain_tools.enqueue_item_processing", new=AsyncMock()) as enqueue,
    ):
        result = await remember_for_mcp(
            db_session, user.id, "the launch date is Friday", title="Launch"
        )

    assert result["created"] is True
    assert result["title"] == "Launch"
    assert f"item={result['id']}" in result["url"]
    enqueue.assert_awaited_once()

    item = (
        await db_session.execute(select(Item).where(Item.id == UUID(result["id"])))
    ).scalar_one()
    assert item.kind == "note"
    assert item.source == "agent"
    assert item.body == "the launch date is Friday"

    # Identical memory dedupes to the same item, no second enqueue.
    with (
        patch("app.core.item_ingest.generate_embeddings", _embed),
        patch("app.core.mcp_brain_tools.enqueue_item_processing", new=AsyncMock()) as enqueue2,
    ):
        again = await remember_for_mcp(
            db_session, user.id, "the launch date is Friday", title="Launch"
        )
    assert again["created"] is False
    assert again["id"] == result["id"]
    enqueue2.assert_not_awaited()


async def test_remember_for_mcp_rejects_empty_and_oversized(db_session) -> None:
    user = await _make_user(db_session)
    with pytest.raises(ValueError, match="Nothing to remember"):
        await remember_for_mcp(db_session, user.id, "   ")
    with pytest.raises(ValueError, match="too long"):
        await remember_for_mcp(db_session, user.id, "x" * (REMEMBER_MAX_CHARS + 1))
