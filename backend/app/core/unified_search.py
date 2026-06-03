"""Unified RRF search across recordings (segments) AND items (item_chunks).

Powers the "search everything" box of the unified feed. Each source is ranked
independently by FTS rank and by semantic distance; the two rank lists are
fused with Reciprocal Rank Fusion (k=60), then a mild recency boost is applied
so newer hits float up (wai-rocks recency boost; gbrain/wai-brain RRF).

Returns a flat list of ``UnifiedHit`` discriminated by ``source_kind``
("recording" | "item"). Reuses the same Russian-FTS + pgvector machinery as
the recordings-only ``/search`` route (no new infra).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import format_embedding, generate_embedding

logger = logging.getLogger(__name__)

RRF_K = 60
# Recency half-life: a hit loses ~half its boost weight every 30 days.
RECENCY_HALF_LIFE_DAYS = 30.0
RECENCY_WEIGHT = 0.5  # how much recency can add on top of the RRF score


@dataclass
class UnifiedHit:
    source_kind: str  # "recording" | "item"
    parent_id: str  # recording_id or item_id
    chunk_id: str  # segment_id or item_chunk_id
    title: str | None
    kind: str  # recording.type or item.kind
    snippet: str
    score: float
    created_at: str | None


_UNIFIED_SQL = text(
    """
    WITH
    seg_fts AS (
        SELECT s.id AS chunk_id, s.recording_id AS parent_id, s.content,
               r.title, r.type AS kind, r.created_at,
               ROW_NUMBER() OVER (ORDER BY ts_rank(
                   to_tsvector('russian', lower(s.content COLLATE "und-x-icu")),
                   plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))) DESC) AS rn
        FROM segments s JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :uid AND r.deleted_at IS NULL
          AND to_tsvector('russian', lower(s.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))
    ),
    seg_sem AS (
        SELECT s.id AS chunk_id, s.recording_id AS parent_id, s.content,
               r.title, r.type AS kind, r.created_at,
               ROW_NUMBER() OVER (ORDER BY s.embedding <=> CAST(:emb AS vector)) AS rn
        FROM segments s JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :uid AND r.deleted_at IS NULL AND s.embedding IS NOT NULL
        ORDER BY s.embedding <=> CAST(:emb AS vector)
        LIMIT :pool
    ),
    item_fts AS (
        SELECT ic.id AS chunk_id, i.id AS parent_id, ic.content,
               i.title, i.kind, i.created_at,
               ROW_NUMBER() OVER (ORDER BY ts_rank(
                   to_tsvector('russian', lower(ic.content COLLATE "und-x-icu")),
                   plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))) DESC) AS rn
        FROM item_chunks ic JOIN items i ON ic.item_id = i.id
        WHERE i.user_id = :uid AND i.deleted_at IS NULL
          AND to_tsvector('russian', lower(ic.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))
    ),
    item_sem AS (
        SELECT ic.id AS chunk_id, i.id AS parent_id, ic.content,
               i.title, i.kind, i.created_at,
               ROW_NUMBER() OVER (ORDER BY ic.embedding <=> CAST(:emb AS vector)) AS rn
        FROM item_chunks ic JOIN items i ON ic.item_id = i.id
        WHERE i.user_id = :uid AND i.deleted_at IS NULL AND ic.embedding IS NOT NULL
        ORDER BY ic.embedding <=> CAST(:emb AS vector)
        LIMIT :pool
    ),
    seg_combined AS (
        SELECT COALESCE(f.chunk_id, s.chunk_id) AS chunk_id,
               COALESCE(f.parent_id, s.parent_id) AS parent_id,
               COALESCE(f.content, s.content) AS content,
               COALESCE(f.title, s.title) AS title,
               COALESCE(f.kind, s.kind) AS kind,
               COALESCE(f.created_at, s.created_at) AS created_at,
               'recording' AS source_kind,
               COALESCE(1.0/(:k + f.rn), 0) + COALESCE(1.0/(:k + s.rn), 0) AS rrf
        FROM seg_fts f FULL OUTER JOIN seg_sem s ON f.chunk_id = s.chunk_id
    ),
    item_combined AS (
        SELECT COALESCE(f.chunk_id, s.chunk_id) AS chunk_id,
               COALESCE(f.parent_id, s.parent_id) AS parent_id,
               COALESCE(f.content, s.content) AS content,
               COALESCE(f.title, s.title) AS title,
               COALESCE(f.kind, s.kind) AS kind,
               COALESCE(f.created_at, s.created_at) AS created_at,
               'item' AS source_kind,
               COALESCE(1.0/(:k + f.rn), 0) + COALESCE(1.0/(:k + s.rn), 0) AS rrf
        FROM item_fts f FULL OUTER JOIN item_sem s ON f.chunk_id = s.chunk_id
    ),
    unioned AS (
        SELECT * FROM seg_combined
        UNION ALL
        SELECT * FROM item_combined
    )
    SELECT chunk_id, parent_id, content, title, kind, created_at, source_kind,
           rrf * (1.0 + :rw * exp(
               -GREATEST(EXTRACT(EPOCH FROM (now() - created_at)), 0)
               / (:halflife * 86400.0))) AS score
    FROM unioned
    ORDER BY score DESC
    LIMIT :limit
    """
)


async def unified_search(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    limit: int = 20,
) -> list[UnifiedHit]:
    """RRF search over recordings + items, recency-boosted. Empty query -> []."""
    if not query.strip():
        return []
    embedding = format_embedding(
        await generate_embedding(
            query,
            usage_user_id=user_id,
            usage_feature="search",
            usage_operation="embedding.query",
        )
    )
    pool = max(limit * 3, 30)
    rows = (
        await db.execute(
            _UNIFIED_SQL,
            {
                "q": query,
                "uid": str(user_id),
                "emb": embedding,
                "k": RRF_K,
                "pool": pool,
                "limit": limit,
                "rw": RECENCY_WEIGHT,
                "halflife": RECENCY_HALF_LIFE_DAYS,
            },
        )
    ).fetchall()

    hits: list[UnifiedHit] = []
    for r in rows:
        content = r.content or ""
        hits.append(
            UnifiedHit(
                source_kind=r.source_kind,
                parent_id=str(r.parent_id),
                chunk_id=str(r.chunk_id),
                title=r.title,
                kind=r.kind,
                snippet=content[:280],
                score=float(r.score),
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
        )
    return hits
