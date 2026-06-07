"""Make Wai chats first-class Brain sources.

A Wai chat carries real knowledge — decisions stated, people named, projects
discussed — but until now it was a second-class source: never entity-linked
into the graph, never searchable, invisible to "Ask Brain" unless explicitly
scoped. The mirror could *count* a chat as "needs linking" yet nothing could
ever link it, and the manual button only ever scanned recordings + items.

This module is the single path that turns a conversation into a linked,
searchable Brain citizen:

    gather text -> extract entities (Cerebras) -> seed graph mentions
                -> (re)build embedded chunks for unified search

It runs automatically on turn completion (debounced by a message-count
watermark, see ``tasks/conversation_linking.py``) and as a bounded sweep for
legacy chats (the "Link" button + a nightly backstop). The LLM + embedder are
injectable so unit tests never call a provider. No silent fallback: a failure
linking one conversation propagates to its caller (the sweep isolates per
conversation, exactly like the nightly consolidator).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content import chunk_with_header
from app.core.embeddings import generate_embeddings
from app.core.entity_graph import seed_entities_from_summary
from app.core.summarizer import EntityResult, extract_entities
from app.models.companion import ChatMessage, Conversation, ConversationChunk

logger = logging.getLogger(__name__)

# Minimum complete user+assistant messages before a chat is worth linking — a
# bare "hi" with no reply has nothing durable to extract.
MIN_MESSAGES_TO_LINK = 2
# Cap the text we extract + embed per conversation so a very long thread can't
# blow up token/embedding cost. We keep the most RECENT content (current state
# of the discussion). ~16k chars ≈ a dozen 1200-char chunks.
_CONVERSATION_TEXT_CAP = 16_000
# extract_entities returns these high-level types; map them onto the graph's
# three node types (person / project / topic).
_PERSON_TYPES = {"person", "people"}
_PROJECT_TYPES = {"project", "product"}


@dataclass
class ConversationLinkResult:
    conversation_id: str
    linked: bool
    skipped_reason: str | None
    message_count: int
    mentions_recorded: int
    chunks_written: int
    llm_requests: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "linked": self.linked,
            "skipped_reason": self.skipped_reason,
            "message_count": self.message_count,
            "mentions_recorded": self.mentions_recorded,
            "chunks_written": self.chunks_written,
            "llm_requests": self.llm_requests,
        }


def _message_text(content: Any) -> str:
    """Flatten an OpenAI-style content block (str | dict | list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        for key in ("text", "content", "output_text"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                for key in ("text", "content", "output_text"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
        return " ".join(p for p in parts if p).strip()
    return ""


def _conversation_text(rows: list[tuple[str, Any]]) -> str:
    """Build a ``User: … / Wai: …`` transcript from (role, content) rows,
    keeping the most recent content within the char cap."""
    lines: list[str] = []
    for role, content in rows:
        text = _message_text(content)
        if not text:
            continue
        label = "User" if role == "user" else "Wai"
        lines.append(f"{label}: {text}")
    joined = "\n".join(lines).strip()
    if len(joined) > _CONVERSATION_TEXT_CAP:
        joined = joined[-_CONVERSATION_TEXT_CAP:]
    return joined


def _bucket_entities(
    entities: list[EntityResult],
) -> tuple[list[str], list[str], list[str]]:
    """Split extracted entities into (people, projects, topics) by type."""
    people: list[str] = []
    projects: list[str] = []
    topics: list[str] = []
    for entity in entities:
        name = (entity.name or "").strip()
        if not name:
            continue
        etype = (entity.type or "").strip().lower()
        if etype in _PERSON_TYPES:
            people.append(name)
        elif etype in _PROJECT_TYPES:
            projects.append(name)
        else:
            # organization / topic / theme / anything else -> topic node.
            topics.append(name)
    return people, projects, topics


async def _complete_message_rows(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[tuple[str, Any]]:
    rows = (
        await db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role.in_(("user", "assistant")),
                ChatMessage.status == "complete",
            )
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        )
    ).all()
    return [(role, content) for role, content in rows]


async def link_conversation_to_brain(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    entity_extractor=None,
    embedder=None,
    min_messages: int = MIN_MESSAGES_TO_LINK,
    force: bool = False,
) -> ConversationLinkResult:
    """Link one conversation into the Brain: graph mentions + searchable chunks.

    Debounced by ``conversations.brain_linked_message_count``: if no new
    complete messages arrived since the last successful link, this is a no-op
    (unless ``force``). Returns a result describing what (if anything) changed.
    """
    cid = str(conversation_id)
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        return ConversationLinkResult(cid, False, "not_found", 0, 0, 0, 0)

    rows = await _complete_message_rows(db, conversation_id)
    count = len(rows)
    if count < min_messages:
        return ConversationLinkResult(cid, False, "too_short", count, 0, 0, 0)
    if not force and count == conv.brain_linked_message_count:
        return ConversationLinkResult(cid, False, "unchanged", count, 0, 0, 0)

    text = _conversation_text(rows)
    if not text:
        # Nothing extractable, but mark processed so we don't re-scan it.
        conv.brain_linked_message_count = count
        await db.flush()
        return ConversationLinkResult(cid, False, "empty", count, 0, 0, 0)

    extractor = entity_extractor or extract_entities
    entities = await extractor(text)
    people, projects, topics = _bucket_entities(entities)
    mentions = await seed_entities_from_summary(
        db,
        user_id,
        source_kind="chat",
        source_id=conversation_id,
        people=people,
        topics=topics,
        projects=projects,
    )

    # Rebuild the searchable chunk set from the current transcript so unified
    # search + Ask can cite this chat. Replace wholesale — cheap and keeps
    # chunks in lockstep with the latest content.
    chunks = chunk_with_header(conv.title, text)
    await db.execute(
        delete(ConversationChunk).where(
            ConversationChunk.conversation_id == conversation_id
        )
    )
    if chunks:
        embed_fn = embedder or generate_embeddings
        vectors = await embed_fn(chunks)
        for seq, (chunk_text, vec) in enumerate(zip(chunks, vectors)):
            db.add(
                ConversationChunk(
                    conversation_id=conversation_id,
                    seq=seq,
                    content=chunk_text,
                    embedding=vec,
                )
            )

    conv.brain_linked_message_count = count
    await db.flush()
    logger.info(
        "conversation linked to brain conv=%s msgs=%s mentions=%s chunks=%s",
        cid,
        count,
        mentions,
        len(chunks),
    )
    return ConversationLinkResult(
        conversation_id=cid,
        linked=True,
        skipped_reason=None,
        message_count=count,
        mentions_recorded=mentions,
        chunks_written=len(chunks),
        llm_requests=1,
    )


@dataclass
class UnlinkedConversationSweepResult:
    conversations_scanned: int
    conversations_linked: int
    mentions_recorded: int
    chunks_written: int
    llm_requests: int

    def as_dict(self) -> dict[str, int]:
        return {
            "conversations_scanned": self.conversations_scanned,
            "conversations_linked": self.conversations_linked,
            "mentions_recorded": self.mentions_recorded,
            "chunks_written": self.chunks_written,
            "llm_requests": self.llm_requests,
        }


async def link_unlinked_conversations(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 25,
    entity_extractor=None,
    embedder=None,
) -> UnlinkedConversationSweepResult:
    """Link conversations that were never processed into the Brain.

    Targets chats with no graph mention yet (``brain_linked_message_count == 0``)
    — the legacy backlog behind "the button does nothing". Bounded by ``limit``
    so neither the button nor the nightly backstop can cause a cost spike. One
    failing conversation is isolated and logged, never poisoning the batch.
    """
    candidate_ids = list(
        (
            await db.execute(
                select(Conversation.id)
                .where(
                    Conversation.user_id == user_id,
                    Conversation.deleted_at.is_(None),
                    Conversation.archived_at.is_(None),
                    Conversation.brain_linked_message_count == 0,
                    Conversation.last_message_at.isnot(None),
                )
                .order_by(Conversation.last_message_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )

    scanned = linked = mentions = chunks = llm = 0
    for conversation_id in candidate_ids:
        scanned += 1
        try:
            # Savepoint per conversation: a single bad chat rolls back cleanly
            # and the shared session stays usable for the rest of the sweep.
            async with db.begin_nested():
                result = await link_conversation_to_brain(
                    db,
                    user_id,
                    conversation_id,
                    entity_extractor=entity_extractor,
                    embedder=embedder,
                )
        except Exception:
            logger.exception(
                "failed to link conversation %s to brain", conversation_id
            )
            continue
        llm += result.llm_requests
        if result.linked:
            linked += 1
            mentions += result.mentions_recorded
            chunks += result.chunks_written
    return UnlinkedConversationSweepResult(
        conversations_scanned=scanned,
        conversations_linked=linked,
        mentions_recorded=mentions,
        chunks_written=chunks,
        llm_requests=llm,
    )


async def count_unlinked_conversations(
    db: AsyncSession, user_id: uuid.UUID
) -> int:
    """How many chats have never been linked into the Brain (for honest UI)."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
                Conversation.archived_at.is_(None),
                Conversation.brain_linked_message_count == 0,
                Conversation.last_message_at.isnot(None),
            )
        )
        or 0
    )
