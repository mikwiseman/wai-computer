"""Background processing for a freshly-captured Item.

A ``POST /items`` with a URL but no body stores the raw item instantly
(signal-capture-first) and enqueues this pipeline:

    fetch URL -> store body + re-embed chunks -> summarize + key-moments.

Fetch failures (e.g. Instagram/TikTok "share the file", a transcript-less
video) are NOT silent: the user-facing message is recorded on
``item.metadata["fetch_error"]`` and the item is marked ``state="needs_input"``
so the feed / Telegram reply can tell the user exactly what to do. We never
drop the item or pretend success.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content import chunk_with_header, content_hash, simhash64
from app.core.embeddings import generate_embeddings
from app.core.item_summary import generate_item_summary
from app.core.source_fetch import FetchedContent, SourceFetchError, fetch_url
from app.models.item import Item, ItemChunk

logger = logging.getLogger(__name__)

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]
Fetcher = Callable[[str], Awaitable[FetchedContent]]


async def _embed_item_chunks(
    db: AsyncSession, item: Item, embedder: Embedder
) -> None:
    """Replace an item's chunks with freshly-embedded contextual-header chunks."""
    await db.execute(delete(ItemChunk).where(ItemChunk.item_id == item.id))
    chunks = chunk_with_header(item.title, item.body)
    if not chunks:
        return
    vectors = await embedder(chunks)
    for seq, (text, vec) in enumerate(zip(chunks, vectors)):
        db.add(ItemChunk(item_id=item.id, seq=seq, content=text, embedding=vec))
    await db.flush()


async def process_item(
    db: AsyncSession,
    item: Item,
    *,
    fetcher: Fetcher | None = None,
    embedder: Embedder | None = None,
    summarize: bool = True,
) -> Item:
    """Fetch (if needed), embed, and summarize an item.

    - If the item has a URL but no body, fetch the URL. On a clean
      ``SourceFetchError`` the message is recorded and processing stops (no
      raise — the item survives with a needs_input state).
    - Embeds chunks and (optionally) generates the summary + key-moments.
    """
    fetch_fn = fetcher or fetch_url
    embed_fn = embedder or generate_embeddings

    needs_fetch = bool((item.url or "").strip()) and not (item.body or "").strip()
    if needs_fetch:
        try:
            fetched = await fetch_fn(item.url)
        except SourceFetchError as exc:
            meta = dict(item.metadata_ or {})
            meta["fetch_error"] = {"code": exc.code, "message": exc.message}
            item.metadata_ = meta
            item.state = "needs_input"
            await db.flush()
            logger.info(
                "item fetch surfaced needs_input item=%s code=%s", item.id, exc.code
            )
            return item

        item.body = fetched.body
        item.kind = fetched.kind or item.kind
        if fetched.title and not (item.title or "").strip():
            item.title = fetched.title[:500]
        if fetched.metadata:
            meta = dict(item.metadata_ or {})
            meta.update(fetched.metadata)
            item.metadata_ = meta
        # Body changed from empty -> real content: refresh the dedup fingerprints.
        item.content_hash = content_hash(item.body or item.url)
        item.simhash = simhash64(item.body or item.title)
        await db.flush()

    if not (item.body or "").strip():
        return item

    await _embed_item_chunks(db, item, embed_fn)
    # Doc-level embedding so the item is findable by "similar items".
    doc_vectors = await embed_fn([(item.title or "") + " " + (item.body or "")[:6000]])
    item.embedding = doc_vectors[0]
    await db.flush()

    if summarize:
        await generate_item_summary(db, item)
    return item
