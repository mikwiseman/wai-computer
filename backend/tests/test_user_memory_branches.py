"""Branch tests for app.core.user_memory not exercised by existing tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.user_memory import (
    BLOCK_SPECS,
    MemoryError,
    UserMemoryBlock,
    render_for_prompt,
    write_block,
)
from app.models.user import User


async def _create_user(db: AsyncSession) -> User:
    user = User(
        email=f"um-{uuid.uuid4().hex[:8]}@example.com", password_hash="hash",
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# write_block — validation branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_block_rejects_unknown_label(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    with pytest.raises(MemoryError, match="unknown memory block label"):
        await write_block(
            db_session, user.id,
            label="not_a_real_block", operation="append", content="x",
        )


@pytest.mark.asyncio
async def test_write_block_rejects_non_string_content(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    with pytest.raises(MemoryError, match="content must be a string"):
        await write_block(
            db_session, user.id,
            label="human", operation="append", content=123,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_write_block_append_rejects_empty_content(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    with pytest.raises(MemoryError, match="non-empty content"):
        await write_block(
            db_session, user.id,
            label="human", operation="append", content="   ",
        )


@pytest.mark.asyncio
async def test_write_block_replace_line_requires_target(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    with pytest.raises(MemoryError, match="target_line"):
        await write_block(
            db_session, user.id,
            label="human", operation="replace_line", content="x",
            target_line=None,
        )


@pytest.mark.asyncio
async def test_write_block_replace_line_target_not_found(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    # Seed something first so block is non-empty
    await write_block(
        db_session, user.id,
        label="human", operation="append", content="existing line",
    )
    with pytest.raises(MemoryError, match="not found"):
        await write_block(
            db_session, user.id,
            label="human", operation="replace_line", content="replacement",
            target_line="ghost line",
        )


@pytest.mark.asyncio
async def test_write_block_unknown_operation(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    with pytest.raises(MemoryError, match="unknown operation"):
        await write_block(
            db_session, user.id,
            label="human", operation="invalid_op", content="x",
        )


@pytest.mark.asyncio
async def test_write_block_seed_reserved_for_system(db_session: AsyncSession) -> None:
    """seed operation requires source='system'; agent source is rejected."""
    user = await _create_user(db_session)
    with pytest.raises(MemoryError, match="reserved for system"):
        await write_block(
            db_session, user.id,
            label="human", operation="seed", content="hello",
            source="agent",
        )


@pytest.mark.asyncio
async def test_write_block_seed_works_for_system_source(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    result = await write_block(
        db_session, user.id,
        label="human", operation="seed", content="initial",
        source="system",
    )
    assert result.after == "initial"


@pytest.mark.asyncio
async def test_write_block_exceeds_char_limit(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    # human block has char_limit 2000 per BLOCK_SPECS; push past it
    huge = "x" * 5000
    with pytest.raises(MemoryError, match="char_limit"):
        await write_block(
            db_session, user.id,
            label="human", operation="rewrite", content=huge,
        )


@pytest.mark.asyncio
async def test_write_block_replace_line_with_empty_content_removes_line(
    db_session: AsyncSession,
) -> None:
    """If content is empty, the matched line is removed entirely."""
    user = await _create_user(db_session)
    await write_block(
        db_session, user.id,
        label="topics", operation="append", content="keep me",
    )
    await write_block(
        db_session, user.id,
        label="topics", operation="append", content="remove me",
    )
    result = await write_block(
        db_session, user.id,
        label="topics", operation="replace_line", content="",
        target_line="remove me",
    )
    assert "keep me" in result.after
    assert "remove me" not in result.after


# ---------------------------------------------------------------------------
# render_for_prompt — None block branch
# ---------------------------------------------------------------------------


def test_render_for_prompt_skips_missing_block() -> None:
    """When a block is missing from the dict, the function skips silently."""
    fake_block = UserMemoryBlock(
        user_id=uuid.uuid4(),
        label="human", body="real content", char_limit=2000,
    )
    # Provide only one block; the other BLOCK_SPECS entries trigger `if block
    # is None: continue` on line 193.
    blocks: dict[str, UserMemoryBlock] = {"human": fake_block}
    rendered = render_for_prompt(blocks)
    assert "<memory>" in rendered
    assert "real content" in rendered


def test_render_for_prompt_all_empty_returns_empty() -> None:
    blocks: dict[str, UserMemoryBlock] = {
        label: UserMemoryBlock(
            user_id=uuid.uuid4(), label=label, body="", char_limit=2000,
        )
        for label in BLOCK_SPECS
    }
    assert render_for_prompt(blocks) == ""


def test_render_for_prompt_no_blocks_returns_empty() -> None:
    assert render_for_prompt({}) == ""
