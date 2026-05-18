"""Wai long-term memory — single source of truth for reading + writing
user memory blocks.

Pattern (Letta core-block × gbrain compiled-truth × Karpathy wiki):
- A small fixed set of labelled markdown blocks per user lives in
  user_memory_blocks. The agent edits them via the `remember` tool, and
  a nightly consolidator updates them from new conversations + recordings.
- Blocks render into the cacheable system prefix on every turn so the
  model never has to "ask" for who the user is — durable facts are
  always in context.
- char_limit is enforced server-side so a runaway tool call cannot blow
  the prompt cache or context window.
- Every write goes through `write_block`, which appends to user_memory_log
  for audit + rollback (gbrain log.md pattern).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_memory import UserMemoryBlock, UserMemoryLogEntry

# Block contract: label → (char_limit, seed body shown to the user/agent
# until first edit). Order here is also the render order in <memory>.
BLOCK_SPECS: dict[str, tuple[int, str]] = {
    "human": (
        4000,
        "Durable facts about the user — name, location, goals, "
        "relationships, ongoing projects. Add a new bullet line per fact.",
    ),
    "topics": (
        4000,
        "Recurring topics across the user's recordings. One short bullet "
        "per topic plus a few keywords.",
    ),
    "preferences": (
        1500,
        "How the user likes to be answered. Style, length, language "
        "nuances, terms to use or avoid.",
    ),
}

Operation = Literal["append", "replace_line", "rewrite", "seed"]
Source = Literal["agent", "user", "consolidator", "system"]


@dataclass
class WriteResult:
    block: UserMemoryBlock
    before: str
    after: str


class MemoryError(Exception):
    """Block-write rejected (unknown label, over the char limit, missing
    target_line, etc.). Surfaced to the agent as a tool error so it can
    try a different operation or give up."""


async def get_or_seed_blocks(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, UserMemoryBlock]:
    """Return the user's blocks keyed by label, creating empty rows for
    any label in BLOCK_SPECS that doesn't yet exist."""
    stmt = select(UserMemoryBlock).where(UserMemoryBlock.user_id == user_id)
    result = await db.execute(stmt)
    by_label = {b.label: b for b in result.scalars().all()}
    missing = [label for label in BLOCK_SPECS if label not in by_label]
    if not missing:
        return by_label
    for label in missing:
        char_limit, _seed = BLOCK_SPECS[label]
        block = UserMemoryBlock(
            user_id=user_id,
            label=label,
            body="",
            char_limit=char_limit,
            updated_by="system",
        )
        db.add(block)
        by_label[label] = block
    await db.flush()
    return by_label


def _normalize_lines(text: str) -> list[str]:
    """Split body into trimmed lines for replace_line operations."""
    return [line.rstrip() for line in text.splitlines()]


async def write_block(
    db: AsyncSession,
    user_id: uuid.UUID,
    label: str,
    operation: Operation,
    content: str,
    *,
    target_line: str | None = None,
    source: Source = "agent",
    conversation_id: uuid.UUID | None = None,
) -> WriteResult:
    """Apply a single memory write. Raises MemoryError on any policy
    violation (no fallbacks — fix the call, not the result).
    """
    if label not in BLOCK_SPECS:
        raise MemoryError(f"unknown memory block label: {label!r}")
    if not isinstance(content, str):
        raise MemoryError("content must be a string")
    content = content.strip()
    if operation == "replace_line" and not target_line:
        raise MemoryError("replace_line requires target_line")

    blocks = await get_or_seed_blocks(db, user_id)
    block = blocks[label]
    before = block.body

    if operation == "append":
        if not content:
            raise MemoryError("append requires non-empty content")
        prefix = before.rstrip()
        if prefix and not prefix.endswith("\n"):
            prefix = prefix + "\n"
        new_body = prefix + content
    elif operation == "replace_line":
        lines = _normalize_lines(before)
        target_normalised = (target_line or "").strip().rstrip()
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            if not replaced and line.strip() == target_normalised:
                if content:
                    new_lines.append(content)
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            raise MemoryError(
                f"replace_line: target_line not found in block {label!r}"
            )
        new_body = "\n".join(new_lines)
    elif operation == "rewrite":
        new_body = content
    elif operation == "seed":
        # Internal-only: only the system may seed.
        if source != "system":
            raise MemoryError("seed operation reserved for system source")
        new_body = content
    else:
        raise MemoryError(f"unknown operation: {operation!r}")

    new_body = new_body.strip()
    if len(new_body) > block.char_limit:
        raise MemoryError(
            f"block {label!r} char_limit exceeded "
            f"({len(new_body)}/{block.char_limit}) — try replace_line or "
            f"rewrite a tighter version"
        )

    block.body = new_body
    block.updated_by = source

    db.add(
        UserMemoryLogEntry(
            user_id=user_id,
            label=label,
            operation=operation,
            before_body=before,
            after_body=new_body,
            source=source,
            conversation_id=conversation_id,
        )
    )
    await db.flush()
    return WriteResult(block=block, before=before, after=new_body)


def render_for_prompt(blocks: dict[str, UserMemoryBlock]) -> str:
    """Compact <memory> section for the cacheable system prefix.

    Returns "" when every block is empty — keeps the prompt minimal for
    fresh users so the cache prefix can still cross the 1024-token warm
    threshold via identity + tool_guidance + answer_format alone.
    """
    sections: list[str] = []
    for label in BLOCK_SPECS:
        block = blocks.get(label)
        if block is None:
            continue
        body = (block.body or "").strip()
        if not body:
            continue
        sections.append(f"## {label}\n{body}")
    if not sections:
        return ""
    return "<memory>\n" + "\n\n".join(sections) + "\n</memory>"
