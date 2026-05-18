#!/usr/bin/env python3
"""One-off backfill: re-embed every segment with text-embedding-3-large.

Run once after the 20260518_130000_resize_segment_embedding migration deploys.
Iterates segments with a NULL embedding, calls OpenAI in batches, writes the
new 3072-dim column. Resumable — segments that already have an embedding are
skipped, so the script can be killed and restarted safely.

Usage (after migration completes):
    cd backend
    .venv/bin/python ../scripts/reembed-segments.py

Reads OPENAI_API_KEY and DATABASE_URL from the backend's normal settings
(.env or environment).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import generate_embeddings
from app.db.session import async_session_maker
from app.models.recording import Segment

BATCH_SIZE = 128

logger = logging.getLogger("reembed-segments")


async def _count_pending(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(Segment.id)).where(Segment.embedding.is_(None))
    )
    return int(result.scalar_one())


async def _fetch_batch(db: AsyncSession) -> list[Segment]:
    result = await db.execute(
        select(Segment).where(Segment.embedding.is_(None)).limit(BATCH_SIZE)
    )
    return list(result.scalars().all())


async def reembed_all() -> None:
    async with async_session_maker() as db:
        remaining = await _count_pending(db)
    logger.info("segments without embedding: %d", remaining)

    if remaining == 0:
        logger.info("nothing to do")
        return

    processed = 0
    while True:
        async with async_session_maker() as db:
            batch = await _fetch_batch(db)
            if not batch:
                break
            texts = [s.content for s in batch]
            embeddings = await generate_embeddings(texts)
            for segment, embedding in zip(batch, embeddings, strict=True):
                await db.execute(
                    update(Segment)
                    .where(Segment.id == segment.id)
                    .values(embedding=embedding)
                )
            await db.commit()
            processed += len(batch)
            logger.info("re-embedded %d / %d", processed, remaining)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(reembed_all())
    return 0


if __name__ == "__main__":
    sys.exit(main())
