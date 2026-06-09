"""create_safety on remember() — agent write-quality (m50/m46)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.mcp_brain_tools import remember_for_mcp
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _constant_embedder(texts):
    # Identical embedding for every text -> any second memory is a near-dup,
    # which lets us exercise the embedding-distance path deterministically.
    return [[0.02] * 1536 for _ in texts]


async def _make_user(db) -> User:
    user = User(email=f"cs-{uuid4().hex}@example.com", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def test_first_is_novel_then_semantic_near_dup_is_exists(db_session) -> None:
    user = await _make_user(db_session)
    with (
        patch("app.core.item_ingest.generate_embeddings", _constant_embedder),
        patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"),
    ):
        first = await remember_for_mcp(db_session, user.id, "I prefer morning meetings", title="A")
        assert first["create_safety"] == "novel"  # nothing similar yet

        # Different text (new row) but an identical embedding -> flagged as a near-dup.
        second = await remember_for_mcp(
            db_session, user.id, "Mornings are best for meetings", title="B"
        )
        assert second["created"] is True
        assert second["create_safety"] == "exists"
        assert second["similar_id"] == first["id"]


async def test_exact_duplicate_is_exists(db_session) -> None:
    user = await _make_user(db_session)
    with (
        patch("app.core.item_ingest.generate_embeddings", _constant_embedder),
        patch("app.tasks.item_summary_generation.generate_item_summary_task.delay"),
    ):
        await remember_for_mcp(db_session, user.id, "same fact", title="T")
        again = await remember_for_mcp(db_session, user.id, "same fact", title="T")
        assert again["created"] is False  # exact content_hash dedup
        assert again["create_safety"] == "exists"
