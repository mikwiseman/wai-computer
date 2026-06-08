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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.brain_ask import ask_brain
from app.core.conversation_brain import _message_text
from app.core.mcp_tools import (
    _as_uuid,
    _iso,
    _truncate_text,
    _validate_limit,
    fetch_recording_for_mcp,
)
from app.core.unified_search import unified_search
from app.models.companion import ChatMessage, Conversation
from app.models.item import Item, ItemSummary

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

    hits = await unified_search(db, _as_uuid(user_id), query, limit=limit)
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
