"""Tests for the wake_up() MCP tier (P5) — cheap agent bootstrap."""

from uuid import uuid4

import pytest

from app.core import user_memory
from app.core.entity_graph import record_mention, upsert_entity
from app.core.mcp_brain_tools import wake_up_for_mcp
from app.models.item import Item
from app.models.recording import Folder
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"wake-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_wake_up_returns_profile_taxonomy_protocol(db_session) -> None:
    user = await _make_user(db_session)

    # Durable memory block -> profile.
    blocks = await user_memory.get_or_seed_blocks(db_session, user.id)
    blocks[next(iter(blocks))].body = "Allergic to penicillin."
    # Folder -> taxonomy.
    db_session.add(Folder(user_id=user.id, name="Investors"))
    # Entity + mention -> top_entities.
    ent = await upsert_entity(db_session, user.id, type="person", name="Pavel")
    item = Item(
        user_id=user.id,
        source="paste",
        kind="note",
        title="Investor note",
        body="Pavel mentioned the round.",
        content_hash=f"wake-{uuid4().hex}",
    )
    db_session.add(item)
    await db_session.flush()
    await record_mention(
        db_session, user_id=user.id, entity_id=ent.id, source_kind="item", source_id=item.id
    )
    await db_session.flush()

    result = await wake_up_for_mcp(db_session, user.id)
    assert "penicillin" in result["profile"].lower()
    assert "Investors" in result["taxonomy"]["folders"]
    assert "Pavel" in result["taxonomy"]["top_entities"]
    protocol = result["protocol"].lower()
    assert "ask" in protocol and "never guess" in protocol  # recall-before-asserting


async def test_wake_up_empty_user_is_safe(db_session) -> None:
    user = await _make_user(db_session)
    result = await wake_up_for_mcp(db_session, user.id)
    assert result["profile"] == ""  # no blocks written yet
    assert result["taxonomy"]["folders"] == []
    assert result["taxonomy"]["top_entities"] == []
    assert result["protocol"]  # protocol always present


async def test_wake_up_ignores_orphan_mentions(db_session) -> None:
    user = await _make_user(db_session)
    ent = await upsert_entity(db_session, user.id, type="person", name="Orphaned")
    await record_mention(
        db_session,
        user_id=user.id,
        entity_id=ent.id,
        source_kind="item",
        source_id=uuid4(),
    )
    await db_session.flush()

    result = await wake_up_for_mcp(db_session, user.id)
    assert "Orphaned" not in result["taxonomy"]["top_entities"]
