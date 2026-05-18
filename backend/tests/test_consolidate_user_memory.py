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
                    },
                    {
                        "block": "topics",
                        "operation": "append",
                        "content": "v0.2.0 (in progress)",
                    },
                ]
            }
        )

        result = await _consolidate_one_user(
            db_session, user.id, openai_client=fake
        )
        assert result["updates_applied"] == 2
        assert result["updates_rejected"] == 0
        assert result["considered"] == 2

        blocks = await get_or_seed_blocks(db_session, user.id)
        assert "Reykjavik" in blocks["human"].body
        assert "v0.2.0" in blocks["topics"].body
        # 'consolidator' source is recorded on the block.
        assert blocks["human"].updated_by == "consolidator"

    async def test_rejects_bad_updates_without_crashing_batch(
        self, db_session, seeded_user_with_activity
    ):
        user = seeded_user_with_activity
        fake = _FakeOpenAI(
            payload={
                "updates": [
                    {
                        "block": "human",
                        "operation": "append",
                        "content": "Lives in Reykjavik",
                    },
                    {
                        "block": "preferences",
                        "operation": "rewrite",
                        "content": "x" * 2000,  # over char_limit (1500)
                    },
                ]
            }
        )
        result = await _consolidate_one_user(
            db_session, user.id, openai_client=fake
        )
        assert result["updates_applied"] == 1
        assert result["updates_rejected"] == 1

        blocks = await get_or_seed_blocks(db_session, user.id)
        assert "Reykjavik" in blocks["human"].body
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
