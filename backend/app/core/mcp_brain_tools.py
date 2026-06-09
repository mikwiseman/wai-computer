"""Brain-level MCP tools — the WaiComputer MCP server as a real second brain.

The recordings-only helpers in :mod:`app.core.mcp_tools` let a connected agent
read transcripts. These turn the same MCP endpoint into the agent's *memory*:

- ``ask``    — one cited answer synthesized across recordings + items + chats.
- ``search`` — unified RRF search across all three source kinds (not just
  recordings), so "what do I know about X" reaches everything captured.
- ``fetch``  — open any recording / item / chat by id (polymorphic).
- ``remember`` — store a new memory back into the brain (memory:write only).

Read paths reuse :func:`app.core.brain_ask.ask_brain` and
:func:`app.core.unified_search.unified_search` verbatim; the write path reuses
:func:`app.core.item_ingest.ingest_item` — the identical intake the web "add
anything" capture uses — so an agent-saved memory flows through the same
entity / dossier / search pipeline as everything else. No parallel pipeline,
no fallbacks: one source of truth per concern.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core import user_memory
from app.core.brain_ask import ask_brain
from app.core.conversation_brain import _message_text
from app.core.item_ingest import enqueue_item_processing, ingest_item
from app.core.mcp_tools import (
    _as_uuid,
    _iso,
    _truncate_text,
    _validate_limit,
    fetch_recording_for_mcp,
)
from app.core.reranker import get_reranker, rerank_hits
from app.core.unified_search import unified_search
from app.models.companion import ChatMessage, Conversation
from app.models.entity import Entity, EntityMention
from app.models.item import Item, ItemSummary
from app.models.recording import Folder

logger = logging.getLogger(__name__)

# Cap a single remembered memory so one tool call can't dump a whole document
# into the note store (use the recording/file import path for big content).
REMEMBER_MAX_CHARS = 20_000

_SOURCE_QUERY_KEY = {"recording": "recording", "item": "item", "chat": "chat"}
_DEFAULT_TITLE = {
    "recording": "Untitled Recording",
    "item": "Untitled note",
    "chat": "Chat",
}


def _source_url(source_kind: str, source_id: str) -> str:
    """Deep link a brain source to its WaiComputer dashboard view."""
    base = get_settings().frontend_url.rstrip("/")
    key = _SOURCE_QUERY_KEY.get(source_kind, "recording")
    return f"{base}/dashboard?{key}={source_id}"


_WAKE_PROTOCOL = (
    "Wai is the user's second brain. On a new session call wake_up() ONCE to load "
    "their profile + taxonomy. Before asserting any fact about the user's life, "
    "people, projects, or past decisions, call ask() (or search()) FIRST and ground "
    "the answer in what it returns — never guess. Use remember() only for durable "
    "facts the user asked to keep. Wrong is worse than slow."
)
# ~800 tokens — a cheap always-on identity payload, not the whole brain.
_PROFILE_CHAR_CAP = 3200
_WAKE_TOP_ENTITIES = 12


async def wake_up_for_mcp(db: AsyncSession, user_id: str | UUID) -> dict:
    """A cheap wake-up payload so a connecting agent boots 'knowing the user'.

    Returns ``{profile, taxonomy, protocol}``: the compiled durable memory blocks
    (~800 tokens), the folder + top-entity taxonomy for scoping, and the
    recall-before-asserting protocol. Zero new LLM — it reads already-compiled
    state, so it is the token-cheap way to make a connected agent context-aware on
    its first turn.
    """
    user_uuid = _as_uuid(user_id)
    blocks = await user_memory.get_or_seed_blocks(db, user_uuid)
    profile = user_memory.render_for_prompt(blocks)[:_PROFILE_CHAR_CAP]

    folders = (
        await db.execute(
            select(Folder.name).where(Folder.user_id == user_uuid).order_by(Folder.name)
        )
    ).scalars().all()

    entity_rows = (
        await db.execute(
            select(Entity.name, func.count(EntityMention.id).label("mentions"))
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .where(Entity.user_id == user_uuid)
            .group_by(Entity.id, Entity.name)
            .order_by(desc("mentions"))
            .limit(_WAKE_TOP_ENTITIES)
        )
    ).all()

    return {
        "profile": profile,
        "taxonomy": {
            "folders": list(folders),
            "top_entities": [name for (name, _count) in entity_rows],
        },
        "protocol": _WAKE_PROTOCOL,
    }


async def ask_brain_for_mcp(db: AsyncSession, user_id: str | UUID, question: str) -> dict:
    """Answer ``question`` from the user's whole brain, with citations + gaps.

    This is the headline memory tool: instead of making the agent search then
    read, it returns one synthesized, grounded answer across recordings, notes,
    and chats — with a citation list (each fetchable by id) and an honest
    statement of what's missing or stale."""
    answer = await ask_brain(db, _as_uuid(user_id), question)
    return {
        "answer": answer.answer,
        "citations": [
            {
                "id": str(c.source_id),
                "source_kind": c.source_kind,
                "title": c.title,
                "url": _source_url(c.source_kind, str(c.source_id)),
            }
            for c in answer.citations
        ],
        "gaps": answer.gaps,
        "freshness": {
            "newest_source_at": _iso(answer.freshness.newest_source_at),
            "weeks_since": answer.freshness.weeks_since,
            "stale": answer.freshness.stale,
        },
    }


async def search_brain_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    query: str,
    *,
    limit: int = 10,
) -> dict:
    """Unified RRF search across the user's recordings, notes, and chats.

    Each hit carries the parent source id (fetchable via :func:`fetch`), a
    snippet, a dashboard url, and ``metadata.source_kind`` so the agent can tell
    a meeting from a saved note from a Wai chat."""
    settings = get_settings()
    if not query or not query.strip():
        return {"results": []}
    _validate_limit(limit, settings.mcp_max_search_results)

    # Agents (not the as-you-type web box) get reranked results when enabled:
    # over-retrieve a wider pool, then rerank to the requested limit.
    reranker = get_reranker(settings)
    pool = (
        min(limit * settings.reranker_overfetch, settings.reranker_max_candidates)
        if reranker
        else limit
    )
    hits = await unified_search(db, _as_uuid(user_id), query, limit=pool, per_parent_limit=1)
    if reranker:
        hits, _tokens = await rerank_hits(
            query, hits, reranker=reranker, top_k=limit,
            confidence_threshold=settings.reranker_confidence_threshold,
        )
    return {
        "results": [
            {
                "id": hit.parent_id,
                "title": hit.title or _DEFAULT_TITLE.get(hit.source_kind, "Untitled"),
                "text": hit.snippet,
                "url": _source_url(hit.source_kind, hit.parent_id),
                "metadata": {
                    "source_kind": hit.source_kind,
                    "kind": hit.kind,
                    "created_at": hit.created_at,
                    "start_ms": hit.start_ms,
                },
            }
            for hit in hits
        ]
    }


async def _fetch_item_for_mcp(db: AsyncSession, user_uuid: UUID, item_id: UUID) -> dict | None:
    result = await db.execute(
        select(Item)
        .where(
            Item.id == item_id,
            Item.user_id == user_uuid,
            Item.deleted_at.is_(None),
        )
        .options(selectinload(Item.summary))
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None

    summary: ItemSummary | None = item.summary
    sections: list[str] = []
    if summary and summary.summary:
        sections.append(f"Summary:\n{summary.summary}")
    if summary and summary.key_points:
        points = "\n".join(f"- {p}" for p in summary.key_points)
        sections.append(f"Key points:\n{points}")
    if item.body:
        sections.append(item.body)
    text, truncated = _truncate_text("\n\n".join(s for s in sections if s))
    return {
        "id": str(item.id),
        "title": item.title or _DEFAULT_TITLE["item"],
        "text": text,
        "url": _source_url("item", str(item.id)),
        "metadata": {
            "source_kind": "item",
            "kind": item.kind,
            "source_url": item.url,
            "created_at": _iso(item.created_at),
            "occurred_at": _iso(item.occurred_at),
            "truncated": truncated,
        },
    }


async def _fetch_chat_for_mcp(
    db: AsyncSession, user_uuid: UUID, conversation_id: UUID
) -> dict | None:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_uuid,
            Conversation.deleted_at.is_(None),
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        return None

    messages = (
        (
            await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.status == "complete",
                )
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        )
        .scalars()
        .all()
    )
    lines: list[str] = []
    for message in messages:
        body = _message_text(message.content)
        if body:
            lines.append(f"{message.role}: {body}")
    text, truncated = _truncate_text("\n".join(lines))
    return {
        "id": str(conversation.id),
        "title": conversation.title or _DEFAULT_TITLE["chat"],
        "text": text,
        "url": _source_url("chat", str(conversation.id)),
        "metadata": {
            "source_kind": "chat",
            "kind": "chat",
            "created_at": _iso(conversation.created_at),
            "truncated": truncated,
        },
    }


async def fetch_document_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    document_id: str | UUID,
) -> dict | None:
    """Fetch one brain document by id — recording, note, or chat.

    Polymorphic so the ``search``/``ask`` → ``fetch`` loop is coherent across
    every source kind. A recording id resolves exactly as the recordings-only
    ``fetch`` always did (backward compatible); item and chat ids now resolve
    too. Unknown / cross-user / malformed ids return ``None``."""
    user_uuid = _as_uuid(user_id)
    try:
        doc_uuid = _as_uuid(document_id)
    except (ValueError, AttributeError, TypeError):
        return None

    recording = await fetch_recording_for_mcp(db, user_uuid, doc_uuid)
    if recording is not None:
        recording.setdefault("metadata", {})["source_kind"] = "recording"
        return recording

    item = await _fetch_item_for_mcp(db, user_uuid, doc_uuid)
    if item is not None:
        return item

    return await _fetch_chat_for_mcp(db, user_uuid, doc_uuid)


async def remember_for_mcp(
    db: AsyncSession,
    user_id: str | UUID,
    text: str,
    *,
    title: str | None = None,
    source_url: str | None = None,
) -> dict:
    """Store a new memory back into the user's brain (the write half of a
    memory bank).

    The memory is saved as a note via the same :func:`ingest_item` intake the
    web "add anything" capture uses, then enqueued for the same summary +
    entity-linking pipeline — so a future ``ask`` / ``search`` can recall it.
    Idempotent: an identical memory returns the existing item (``created`` is
    False) rather than a duplicate. Caller is responsible for enforcing the
    ``mcp:write`` scope before invoking this."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to remember — provide the memory text.")
    if len(text) > REMEMBER_MAX_CHARS:
        raise ValueError(
            f"Memory is too long (>{REMEMBER_MAX_CHARS} characters). "
            "Save large content as a recording or file import instead."
        )

    clean_title = (title or "").strip() or None
    clean_url = (source_url or "").strip() or None
    item, created = await ingest_item(
        db,
        _as_uuid(user_id),
        source="agent",
        kind="note",
        title=clean_title,
        body=text,
        url=clean_url,
        dedup_key=clean_url or text,
        # Agent-asserted memories rank BELOW first-party captures (default 0.5)
        # and are tagged so synthesis/Review can weight + audit them.
        authority_score=0.3,
        metadata={"origin": "mcp_remember"},
        embed=True,
    )
    await db.flush()
    if created:
        await enqueue_item_processing(db, item)
    result = {
        "id": str(item.id),
        "created": created,
        "title": item.title,
        "url": _source_url("item", str(item.id)),
    }
    # If background processing couldn't be enqueued, the memory IS saved but
    # not yet fully linked — surface that loudly instead of implying success.
    processing_error = (item.metadata_ or {}).get("processing_error")
    if processing_error:
        result["saved_but_processing_pending"] = True
        result["warning"] = processing_error.get(
            "message", "Saved, but background processing hasn't started yet."
        )
    return result


async def forget_for_mcp(db: AsyncSession, user_id: str | UUID, id: str) -> dict:
    """Archive a memory so it stops surfacing in recall — the write-side mirror of
    remember(). Reversible (the item is kept, not deleted) and applies only to
    saved notes/items (recordings + chats aren't agent-forgettable via MCP).
    Caller enforces the ``mcp:write`` scope."""
    try:
        item_uuid = _as_uuid(id)
    except (ValueError, AttributeError):
        raise ValueError("forget expects a memory id from search/remember.") from None
    item = (
        await db.execute(
            select(Item).where(
                Item.id == item_uuid,
                Item.user_id == _as_uuid(user_id),
                Item.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise ValueError("No such memory to forget (only saved notes/items can be forgotten).")
    item.state = "archived"
    await db.flush()
    return {"forgotten": True, "id": str(item.id)}
