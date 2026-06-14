"""Unified RRF search across recordings (segments), items (item_chunks), AND
Wai chats (conversation_chunks).

Powers the "search everything" box of the unified feed AND "Ask Brain". Each
source is ranked independently by FTS rank and by semantic distance; the two
rank lists are fused with Reciprocal Rank Fusion (k=60), then a mild recency
boost is applied so newer hits float up (wai-rocks recency boost; gbrain/
wai-brain RRF).

Returns a flat list of ``UnifiedHit`` discriminated by ``source_kind``
("recording" | "item" | "chat"). Reuses the same Russian-FTS + pgvector
machinery as the recordings-only ``/search`` route (no new infra).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embeddings import format_embedding, generate_embedding
from app.core.vector_search import configure_vector_search

logger = logging.getLogger(__name__)

RRF_K = 60
# Recency half-life: a hit loses ~half its boost weight every 30 days.
RECENCY_HALF_LIFE_DAYS = 30.0
RECENCY_WEIGHT = 0.5  # how much recency can add on top of the RRF score


@dataclass
class UnifiedHit:
    source_kind: str  # "recording" | "item" | "chat"
    parent_id: str  # recording_id, item_id, or conversation_id
    chunk_id: str  # segment_id, item_chunk_id, or conversation_chunk_id
    title: str | None
    kind: str  # recording.type or item.kind
    snippet: str
    score: float
    created_at: str | None
    start_ms: int | None = None
    end_ms: int | None = None


_UNIFIED_SQL = text(
    """
    WITH
    seg_fts AS (
        SELECT s.id AS chunk_id, s.recording_id AS parent_id, s.content,
               r.title, r.type AS kind, r.created_at, s.start_ms, s.end_ms,
               ROW_NUMBER() OVER (ORDER BY ts_rank(
                   to_tsvector('russian', lower(s.content COLLATE "und-x-icu")),
                   plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))) DESC) AS rn
        FROM segments s JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :uid AND r.deleted_at IS NULL
          AND (CAST(:folder_ids AS uuid[]) IS NULL
               OR r.folder_id = ANY(CAST(:folder_ids AS uuid[])))
          AND to_tsvector('russian', lower(s.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))
    ),
    seg_sem AS (
        SELECT s.id AS chunk_id, s.recording_id AS parent_id, s.content,
               r.title, r.type AS kind, r.created_at, s.start_ms, s.end_ms,
               ROW_NUMBER() OVER (ORDER BY s.embedding <=> CAST(:emb AS vector)) AS rn
        FROM segments s JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :uid AND r.deleted_at IS NULL AND s.embedding IS NOT NULL
          AND (CAST(:folder_ids AS uuid[]) IS NULL
               OR r.folder_id = ANY(CAST(:folder_ids AS uuid[])))
        ORDER BY s.embedding <=> CAST(:emb AS vector)
        LIMIT :pool
    ),
    item_fts AS (
        SELECT ic.id AS chunk_id, i.id AS parent_id, ic.content,
               i.title, i.kind, i.created_at, NULL::integer AS start_ms, NULL::integer AS end_ms,
               ROW_NUMBER() OVER (ORDER BY ts_rank(
                   to_tsvector('russian', lower(ic.content COLLATE "und-x-icu")),
                   plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))) DESC) AS rn
        FROM item_chunks ic JOIN items i ON ic.item_id = i.id
        WHERE i.user_id = :uid AND i.deleted_at IS NULL AND i.state IS DISTINCT FROM 'archived'
          AND (CAST(:folder_ids AS uuid[]) IS NULL
               OR i.folder_id = ANY(CAST(:folder_ids AS uuid[])))
          AND to_tsvector('russian', lower(ic.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))
    ),
    item_sem AS (
        SELECT ic.id AS chunk_id, i.id AS parent_id, ic.content,
               i.title, i.kind, i.created_at, NULL::integer AS start_ms, NULL::integer AS end_ms,
               ROW_NUMBER() OVER (ORDER BY ic.embedding <=> CAST(:emb AS vector)) AS rn
        FROM item_chunks ic JOIN items i ON ic.item_id = i.id
        WHERE i.user_id = :uid AND i.deleted_at IS NULL AND i.state IS DISTINCT FROM 'archived'
          AND (CAST(:folder_ids AS uuid[]) IS NULL
               OR i.folder_id = ANY(CAST(:folder_ids AS uuid[])))
          AND ic.embedding IS NOT NULL
        ORDER BY ic.embedding <=> CAST(:emb AS vector)
        LIMIT :pool
    ),
    chat_fts AS (
        SELECT cc.id AS chunk_id, c.id AS parent_id, cc.content,
               c.title, 'chat' AS kind,
               COALESCE(c.last_message_at, c.created_at) AS created_at,
               NULL::integer AS start_ms, NULL::integer AS end_ms,
               ROW_NUMBER() OVER (ORDER BY ts_rank(
                   to_tsvector('russian', lower(cc.content COLLATE "und-x-icu")),
                   plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))) DESC) AS rn
        FROM conversation_chunks cc JOIN conversations c ON cc.conversation_id = c.id
        WHERE c.user_id = :uid AND c.deleted_at IS NULL AND c.archived_at IS NULL
          AND CAST(:folder_ids AS uuid[]) IS NULL
          AND to_tsvector('russian', lower(cc.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:q COLLATE "und-x-icu"))
    ),
    chat_sem AS (
        SELECT cc.id AS chunk_id, c.id AS parent_id, cc.content,
               c.title, 'chat' AS kind,
               COALESCE(c.last_message_at, c.created_at) AS created_at,
               NULL::integer AS start_ms, NULL::integer AS end_ms,
               ROW_NUMBER() OVER (ORDER BY cc.embedding <=> CAST(:emb AS vector)) AS rn
        FROM conversation_chunks cc JOIN conversations c ON cc.conversation_id = c.id
        WHERE c.user_id = :uid AND c.deleted_at IS NULL AND c.archived_at IS NULL
          AND CAST(:folder_ids AS uuid[]) IS NULL
          AND cc.embedding IS NOT NULL
        ORDER BY cc.embedding <=> CAST(:emb AS vector)
        LIMIT :pool
    ),
    seg_combined AS (
        SELECT COALESCE(f.chunk_id, s.chunk_id) AS chunk_id,
               COALESCE(f.parent_id, s.parent_id) AS parent_id,
               COALESCE(f.content, s.content) AS content,
               COALESCE(f.title, s.title) AS title,
               COALESCE(f.kind, s.kind) AS kind,
               COALESCE(f.created_at, s.created_at) AS created_at,
               COALESCE(f.start_ms, s.start_ms) AS start_ms,
               COALESCE(f.end_ms, s.end_ms) AS end_ms,
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
               NULL::integer AS start_ms,
               NULL::integer AS end_ms,
               'item' AS source_kind,
               COALESCE(1.0/(:k + f.rn), 0) + COALESCE(1.0/(:k + s.rn), 0) AS rrf
        FROM item_fts f FULL OUTER JOIN item_sem s ON f.chunk_id = s.chunk_id
    ),
    chat_combined AS (
        SELECT COALESCE(f.chunk_id, s.chunk_id) AS chunk_id,
               COALESCE(f.parent_id, s.parent_id) AS parent_id,
               COALESCE(f.content, s.content) AS content,
               COALESCE(f.title, s.title) AS title,
               COALESCE(f.kind, s.kind) AS kind,
               COALESCE(f.created_at, s.created_at) AS created_at,
               NULL::integer AS start_ms,
               NULL::integer AS end_ms,
               'chat' AS source_kind,
               COALESCE(1.0/(:k + f.rn), 0) + COALESCE(1.0/(:k + s.rn), 0) AS rrf
        FROM chat_fts f FULL OUTER JOIN chat_sem s ON f.chunk_id = s.chunk_id
    ),
    unioned AS (
        SELECT * FROM seg_combined
        UNION ALL
        SELECT * FROM item_combined
        UNION ALL
        SELECT * FROM chat_combined
    ),
    scored AS (
        SELECT chunk_id, parent_id, content, title, kind, created_at, start_ms, end_ms, source_kind,
               rrf * (1.0 + :rw * exp(
                   -GREATEST(EXTRACT(EPOCH FROM (now() - created_at)), 0)
                   / (:halflife * 86400.0)))
               -- Trust-weighted ranking (P4), gated: a clamped authority×salience
               -- multiplier per source. :ranking_v2=0 -> ×1.0 (byte-identical).
               * CASE WHEN :ranking_v2 = 1 THEN
                     GREATEST(0.5, LEAST(1.5, 0.5 + COALESCE(
                         CASE source_kind
                             WHEN 'item' THEN
                                 (SELECT authority_score FROM items WHERE id = parent_id)
                             WHEN 'recording' THEN
                                 (SELECT authority_score FROM recordings WHERE id = parent_id)
                             WHEN 'chat' THEN
                                 (SELECT authority_score FROM conversations WHERE id = parent_id)
                         END, 0.5)))
                   * GREATEST(0.75, LEAST(1.25, 0.5 + COALESCE(
                         CASE source_kind
                             WHEN 'item' THEN
                                 (SELECT salience_score FROM items WHERE id = parent_id)
                             WHEN 'recording' THEN
                                 (SELECT salience_score FROM recordings WHERE id = parent_id)
                             WHEN 'chat' THEN
                                 (SELECT salience_score FROM conversations WHERE id = parent_id)
                         END, 0.5)))
                 ELSE 1.0 END AS score
        FROM unioned
    ),
    -- Per-page max-pool (gbrain RETRIEVAL_MAXPOOL): keep only the best
    -- ``:per_parent`` chunk(s) per (source_kind, parent_id) so one long recording
    -- with many mediocre chunks can't occupy multiple top-K slots and bury a
    -- short note. A NULL ``:per_parent`` keeps every chunk (byte-identical to the
    -- pre-max-pool behaviour); search surfaces pass 1, Ask passes 2.
    ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY source_kind, parent_id ORDER BY score DESC, chunk_id
               ) AS parent_rank
        FROM scored
    )
    SELECT chunk_id, parent_id, LEFT(content, 320) AS content, title, kind, created_at,
           start_ms, end_ms, source_kind, score
    FROM ranked
    WHERE CAST(:per_parent AS integer) IS NULL
       OR parent_rank <= CAST(:per_parent AS integer)
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
    per_parent_limit: int | None = None,
    folder_ids: list[str] | None = None,
) -> list[UnifiedHit]:
    """RRF search over recordings + items + chats, recency-boosted. Empty query -> [].

    ``per_parent_limit`` applies a per-page max-pool: at most that many chunks per
    (source_kind, parent_id) survive, keeping each source's strongest chunk(s) so a
    long recording can't crowd out short notes. ``None`` (default) keeps every
    chunk (legacy behaviour); search surfaces pass 1, Ask passes 2.

    ``folder_ids`` scopes results to those folders: recordings AND items whose
    ``folder_id`` matches survive; chats (which have no folder) are excluded.
    ``None`` searches everything; an empty list matches nothing.
    """
    if not query.strip():
        return []
    folder_uuids: list[uuid.UUID] | None = None
    if folder_ids is not None:
        folder_uuids = []
        for raw in folder_ids:
            try:
                folder_uuids.append(uuid.UUID(str(raw)))
            except ValueError:
                continue  # an unknown id can't match anything anyway
    embedding = format_embedding(await generate_embedding(query))
    pool = max(limit * 3, 30)
    ranking_v2 = 1 if get_settings().brain_ranking_v2_enabled else 0
    await configure_vector_search(db)
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
                "per_parent": per_parent_limit,
                "ranking_v2": ranking_v2,
                "folder_ids": folder_uuids,
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
                start_ms=r.start_ms,
                end_ms=r.end_ms,
            )
        )
    return hits
