"""Ingestion service for universal ``Item`` content (Phase 1).

This is the single intake path for anything that is not an audio recording:
a pasted note, a web article, a forwarded link, a PDF, an MCP-pulled row. It
mirrors what ``recording_import`` does for audio, but for text:

    normalize -> idempotency check (content_hash) -> contextual-header chunk
    -> embed (doc + chunks) -> persist Item + ItemChunks (state="raw").

Idempotency: ``(user_id, content_hash)`` is unique, so re-forwarding the same
link/article returns the existing item instead of creating a duplicate (and
never re-embeds) — the cost-control invariant. Callers that have a stable
external key (a URL) before the body is fetched pass ``dedup_key=url`` so the
item is stable across the fetch lifecycle.

The embedder is injectable so unit tests don't call OpenAI; production uses
``app.core.embeddings.generate_embeddings`` (text-embedding-3-large, 1536-d).
No silent fallback: if embedding is requested and fails, the error propagates.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content import chunk_with_header, content_hash, normalize_text, simhash64
from app.core.embeddings import generate_embeddings
from app.models.item import Item, ItemChunk

logger = logging.getLogger(__name__)

# Doc-level embedding input cap (chars). Chunks are embedded in full; the
# document vector is a cheap "find similar items" signal, so a prefix is fine.
_DOC_EMBED_CHARS = 6000

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def _doc_embed_text(title: str | None, body: str | None, url: str | None) -> str:
    basis = normalize_text(f"{title or ''} {body or ''}".strip())
    if basis:
        return basis[:_DOC_EMBED_CHARS]
    return normalize_text(url or "")


async def ingest_item(
    db: AsyncSession,
    user_id: Any,
    *,
    source: str,
    kind: str = "note",
    title: str | None = None,
    body: str | None = None,
    url: str | None = None,
    source_ref: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict | None = None,
    privacy_level: str = "internal",
    authority_score: float = 0.5,
    folder_id: Any | None = None,
    dedup_key: str | None = None,
    embed: bool = True,
    embedder: Embedder | None = None,
) -> tuple[Item, bool]:
    """Idempotently ingest one piece of content.

    Returns ``(item, created)``. When an item with the same
    ``(user_id, content_hash)`` already exists, returns it with
    ``created=False`` and does no embedding work.
    """
    chash = content_hash(dedup_key if dedup_key is not None else (body or url or title))

    existing = await db.execute(
        select(Item).where(Item.user_id == user_id, Item.content_hash == chash)
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        logger.info("item_ingest dedup hit user=%s source=%s", user_id, source)
        return found, False

    chunks = chunk_with_header(title, body)

    doc_embedding: list[float] | None = None
    chunk_vectors: list[list[float] | None] = [None] * len(chunks)
    if embed:
        embed_fn = embedder or generate_embeddings
        doc_text = _doc_embed_text(title, body, url)
        to_embed = [doc_text, *chunks] if doc_text else list(chunks)
        if to_embed:
            vectors = await embed_fn(to_embed)
            if doc_text:
                doc_embedding = vectors[0]
                chunk_vectors = vectors[1:]
            else:
                chunk_vectors = vectors

    item = Item(
        user_id=user_id,
        source=source,
        source_ref=source_ref,
        url=url,
        kind=kind,
        title=title,
        body=body,
        occurred_at=occurred_at,
        content_hash=chash,
        simhash=simhash64(body or title),
        privacy_level=privacy_level,
        authority_score=authority_score,
        state="raw",
        metadata_=metadata,
        embedding=doc_embedding,
        folder_id=folder_id,
    )
    try:
        async with db.begin_nested():
            db.add(item)
            await db.flush()
    except IntegrityError:
        # Concurrent duplicate: another request inserted the same
        # (user_id, content_hash) between our dedup SELECT and this INSERT.
        # Return the winning row — correct idempotency, never a 500.
        logger.info("item_ingest race dedup user=%s source=%s", user_id, source)
        found = (
            await db.execute(
                select(Item).where(
                    Item.user_id == user_id, Item.content_hash == chash
                )
            )
        ).scalar_one()
        return found, False

    for seq, (chunk_text, vec) in enumerate(zip(chunks, chunk_vectors)):
        db.add(
            ItemChunk(
                item_id=item.id,
                seq=seq,
                content=chunk_text,
                embedding=vec,
            )
        )
    await db.flush()
    logger.info(
        "item_ingest created user=%s source=%s kind=%s chunks=%s",
        user_id,
        source,
        kind,
        len(chunks),
    )
    return item, True


async def enqueue_item_processing(db: AsyncSession, item: Item) -> None:
    """Enqueue background processing for a freshly-created Item — fetch (if
    URL-only), embed, summary + key-moments + entity linking.

    Shared by the web "add anything" route and the MCP ``remember`` tool so a
    saved memory flows through the identical pipeline as any captured item. On
    broker failure, mark the item failed with a visible error (no silent
    swallow) so the client can see + retry."""
    try:
        from app.tasks.item_summary_generation import generate_item_summary_task

        generate_item_summary_task.delay(item_id=str(item.id))
    except Exception as exc:  # noqa: BLE001 — broker down: fail loudly, never pretend success
        logger.warning("item enqueue failed item=%s: %s", item.id, type(exc).__name__)
        meta = dict(item.metadata_ or {})
        meta["processing_error"] = {
            "code": "enqueue_failed",
            "message": "Couldn't start processing. Retry shortly.",
        }
        item.metadata_ = meta
        item.state = "failed"
        await db.flush()
