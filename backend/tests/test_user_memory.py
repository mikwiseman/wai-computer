"""Tests for Wai's long-term memory layer (Letta core-block × gbrain log)."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.user_memory import (
    BLOCK_SPECS,
    MemoryError,
    get_or_seed_blocks,
    render_for_prompt,
    write_block,
)
from app.models.user import User
from app.models.user_memory import UserMemoryBlock, UserMemoryLogEntry


@pytest_asyncio.fixture
async def memory_user(db_session):
    user = User(email=f"mem-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    return user


class TestGetOrSeedBlocks:
    async def test_seeds_all_configured_labels_for_new_user(
        self, db_session, memory_user
    ):
        blocks = await get_or_seed_blocks(db_session, memory_user.id)
        assert set(blocks) == set(BLOCK_SPECS)
        for label, (char_limit, _) in BLOCK_SPECS.items():
            assert blocks[label].char_limit == char_limit
            assert blocks[label].body == ""
            assert blocks[label].updated_by == "system"

    async def test_returning_user_does_not_reseed(
        self, db_session, memory_user
    ):
        await get_or_seed_blocks(db_session, memory_user.id)
        blocks2 = await get_or_seed_blocks(db_session, memory_user.id)
        # Same DB rows on second call
        rows = (
            await db_session.execute(
                select(UserMemoryBlock).where(
                    UserMemoryBlock.user_id == memory_user.id
                )
            )
        ).scalars().all()
        assert len(rows) == len(BLOCK_SPECS)
        assert {b.label for b in blocks2.values()} == set(BLOCK_SPECS)


class TestWriteBlock:
    async def test_append_to_empty_block_seeds_and_writes(
        self, db_session, memory_user
    ):
        result = await write_block(
            db_session,
            memory_user.id,
            label="human",
            operation="append",
            content="Lives in Reykjavik",
        )
        assert result.before == ""
        assert result.after == "Lives in Reykjavik"
        assert result.block.body == "Lives in Reykjavik"
        assert result.block.updated_by == "agent"

    async def test_append_concatenates_with_newline(
        self, db_session, memory_user
    ):
        await write_block(
            db_session,
            memory_user.id,
            label="human",
            operation="append",
            content="Lives in Reykjavik",
        )
        await write_block(
            db_session,
            memory_user.id,
            label="human",
            operation="append",
            content="Building WaiComputer",
        )
        blocks = await get_or_seed_blocks(db_session, memory_user.id)
        assert (
            blocks["human"].body
            == "Lives in Reykjavik\nBuilding WaiComputer"
        )

    async def test_replace_line_corrects_one_fact(
        self, db_session, memory_user
    ):
        await write_block(
            db_session, memory_user.id, "human", "append", "Lives in Berlin"
        )
        await write_block(
            db_session, memory_user.id, "human", "append", "Building WaiComputer"
        )
        await write_block(
            db_session,
            memory_user.id,
            "human",
            "replace_line",
            content="Lives in Reykjavik",
            target_line="Lives in Berlin",
        )
        blocks = await get_or_seed_blocks(db_session, memory_user.id)
        assert (
            blocks["human"].body
            == "Lives in Reykjavik\nBuilding WaiComputer"
        )

    async def test_replace_line_missing_target_raises(
        self, db_session, memory_user
    ):
        await write_block(
            db_session, memory_user.id, "human", "append", "Lives in Reykjavik"
        )
        with pytest.raises(MemoryError):
            await write_block(
                db_session,
                memory_user.id,
                "human",
                "replace_line",
                content="x",
                target_line="not present",
            )

    async def test_rewrite_replaces_whole_block(
        self, db_session, memory_user
    ):
        await write_block(
            db_session, memory_user.id, "human", "append", "old"
        )
        await write_block(
            db_session, memory_user.id, "human", "rewrite", "fresh start"
        )
        blocks = await get_or_seed_blocks(db_session, memory_user.id)
        assert blocks["human"].body == "fresh start"

    async def test_unknown_label_raises(self, db_session, memory_user):
        with pytest.raises(MemoryError):
            await write_block(
                db_session,
                memory_user.id,
                "nonsense",
                "append",
                "x",
            )

    async def test_char_limit_enforced(self, db_session, memory_user):
        # preferences has a 1500-char limit
        with pytest.raises(MemoryError):
            await write_block(
                db_session,
                memory_user.id,
                "preferences",
                "rewrite",
                "x" * 2000,
            )

    async def test_log_entry_written_per_call(self, db_session, memory_user):
        await write_block(
            db_session,
            memory_user.id,
            "human",
            "append",
            "Lives in Reykjavik",
            source="agent",
        )
        await write_block(
            db_session,
            memory_user.id,
            "human",
            "append",
            "Loves espresso",
            source="consolidator",
        )
        logs = (
            await db_session.execute(
                select(UserMemoryLogEntry).where(
                    UserMemoryLogEntry.user_id == memory_user.id
                )
            )
        ).scalars().all()
        assert len(logs) == 2
        sources = {entry.source for entry in logs}
        assert sources == {"agent", "consolidator"}

    async def test_seed_operation_reserved_for_system(
        self, db_session, memory_user
    ):
        with pytest.raises(MemoryError):
            await write_block(
                db_session,
                memory_user.id,
                "human",
                "seed",
                "x",
                source="agent",
            )


class TestRenderForPrompt:
    async def test_empty_blocks_render_to_empty_string(
        self, db_session, memory_user
    ):
        blocks = await get_or_seed_blocks(db_session, memory_user.id)
        assert render_for_prompt(blocks) == ""

    async def test_populated_blocks_render_with_labels(
        self, db_session, memory_user
    ):
        await write_block(
            db_session, memory_user.id, "human", "append", "Lives in Reykjavik"
        )
        await write_block(
            db_session,
            memory_user.id,
            "preferences",
            "append",
            "Answer in Russian when the user does.",
        )
        blocks = await get_or_seed_blocks(db_session, memory_user.id)
        rendered = render_for_prompt(blocks)
        assert rendered.startswith("<memory>")
        assert rendered.endswith("</memory>")
        assert "## human" in rendered
        assert "Lives in Reykjavik" in rendered
        assert "## preferences" in rendered
        assert "Answer in Russian" in rendered
        # 'topics' block stays empty, should NOT render a header
        assert "## topics" not in rendered
