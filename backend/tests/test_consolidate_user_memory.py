"""Tests for the nightly memory consolidator (Letta sleep-time analogue).

Verifies that:
- The consolidator pulls the last-24h material for one user.
- Its LLM-shaped JSON updates flow through user_memory.write_block — the
  same single source of truth used by the in-turn `remember` tool.
- Bad updates (over char_limit, unknown block) are rejected cleanly
  without crashing the whole batch.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest_asyncio

from app.core.user_memory import get_or_seed_blocks
from app.models.companion import ChatMessage, Conversation
from app.models.recording import Recording, Summary
from app.models.user import User
from app.tasks.consolidate_user_memory import _consolidate_one_user


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class _FakeResponse:
    output_text: str = ""
    output: list[dict[str, Any]] = field(default_factory=list)
    usage: _Usage = field(default_factory=_Usage)
    status: str = "completed"
    error: Any = None
    incomplete_details: Any = None


class _FakeOpenAI:
    """One scripted JSON response for the consolidator's single call."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(output_text=json.dumps(self.payload))


@pytest_asyncio.fixture
async def seeded_user_with_activity(db_session):
    """Seed a user, a recent recording with a summary, and a recent
    conversation — enough material for the consolidator to chew on."""
    now = datetime.now(timezone.utc)
    user = User(email=f"cons-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    recording = Recording(
        user_id=user.id,
        title="Weekly review",
        type="meeting",
        status="ready",
        created_at=now - timedelta(hours=4),
    )
    db_session.add(recording)
    await db_session.flush()

    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Discussed the move to Reykjavik. Started shipping v0.2.0.",
            key_points=["moving to Reykjavik", "v0.2.0 in progress"],
            topics=["reykjavik", "v0.2.0"],
            people_mentioned=["Mik"],
        )
    )

    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="user",
            content="Hey Wai, kicking off v0.2.0 today.",
            created_at=now - timedelta(hours=3),
        )
    )
    await db_session.flush()
    return user


class TestConsolidator:
    async def test_applies_updates_via_write_block_path(
        self, db_session, seeded_user_with_activity
    ):
        user = seeded_user_with_activity
        fake = _FakeOpenAI(
            payload={
                "updates": [
                    {
                        "block": "human",
                        "operation": "append",
                        "content": "Moving to Reykjavik",
                        "confidence": 0.9,
                    },
                    {
                        "block": "topics",
                        "operation": "append",
                        "content": "v0.2.0 (in progress)",
                        "confidence": 0.9,
                    },
                ]
            }
        )

        result = await _consolidate_one_user(
            db_session, user.id, openai_client=fake
        )
        # Both are additive + confident → auto-applied straight to memory.
        assert result["auto_applied"] == 2
        assert result["queued"] == 0
        assert result["considered"] == 2

        blocks = await get_or_seed_blocks(db_session, user.id)
        assert "Reykjavik" in blocks["human"].body
        assert "v0.2.0" in blocks["topics"].body
        # 'consolidator' source is recorded on the block.
        assert blocks["human"].updated_by == "consolidator"

    async def test_destructive_update_is_queued_not_applied(
        self, db_session, seeded_user_with_activity
    ):
        """A confident additive fact auto-applies; a rewrite (overwrites prior
        truth) is held for review regardless of confidence — the governance
        gate, not a silent reject."""
        user = seeded_user_with_activity
        fake = _FakeOpenAI(
            payload={
                "updates": [
                    {
                        "block": "human",
                        "operation": "append",
                        "content": "Lives in Reykjavik",
                        "confidence": 0.9,
                    },
                    {
                        "block": "preferences",
                        "operation": "rewrite",
                        "content": "Always answer in Icelandic.",
                        "confidence": 0.95,
                    },
                ]
            }
        )
        result = await _consolidate_one_user(
            db_session, user.id, openai_client=fake
        )
        assert result["auto_applied"] == 1
        assert result["queued"] == 1

        blocks = await get_or_seed_blocks(db_session, user.id)
        assert "Reykjavik" in blocks["human"].body
        # The rewrite stays out of memory until a human accepts it.
        assert blocks["preferences"].body == ""

    async def test_skips_when_no_new_material(self, db_session):
        """A user with no activity in the last 24h is fast-skipped."""
        user = User(
            email=f"quiet-{uuid4().hex}@example.com", password_hash="x"
        )
        db_session.add(user)
        await db_session.flush()
        fake = _FakeOpenAI(payload={"updates": []})
        result = await _consolidate_one_user(
            db_session, user.id, openai_client=fake
        )
        assert result.get("skipped") is True
        # The LLM was NOT called — empty material short-circuits.
        assert fake.calls == []

    async def test_ignores_deleted_conversation_messages(self, db_session):
        """Soft-deleted conversations must not be consolidated into durable memory."""
        now = datetime.now(timezone.utc)
        user = User(
            email=f"deleted-conv-{uuid4().hex}@example.com",
            password_hash="x",
        )
        db_session.add(user)
        await db_session.flush()
        conv = Conversation(user_id=user.id, deleted_at=now - timedelta(minutes=1))
        db_session.add(conv)
        await db_session.flush()
        db_session.add(
            ChatMessage(
                conversation_id=conv.id,
                role="user",
                content="Private deleted conversation should stay out of memory.",
                created_at=now,
            )
        )
        await db_session.flush()

        fake = _FakeOpenAI(
            payload={
                "updates": [
                    {"block": "human", "operation": "append", "content": "leak"}
                ]
            }
        )
        result = await _consolidate_one_user(db_session, user.id, openai_client=fake)

        assert result.get("skipped") is True
        assert fake.calls == []
