"""Shared retrieval helpers used by the Companion turn loop.

The legacy stateless /api/qa route was retired in phase 9 once every client
migrated to the streaming Companion endpoint. The hybrid-search retrieval
itself is reused unchanged.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import format_embedding, generate_embedding
from app.core.observability import safe_text_digest

logger = logging.getLogger(__name__)


@dataclass
class SourceSegment:
    """A source segment returned by retrieval — also re-exported to Companion."""

    segment_id: str
    recording_id: str
    recording_title: str | None
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None


async def retrieve_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    recording_ids: list[uuid.UUID] | None = None,
    limit: int = 15,
) -> list:
    """Retrieve relevant transcript segments using hybrid search (RRF)."""
    query_embedding_list = await generate_embedding(question)
    query_embedding = format_embedding(query_embedding_list)

    recording_filter = ""
    if recording_ids:
        recording_filter = "AND s.recording_id = ANY(:recording_ids)"

    hybrid_query = text("""
        WITH fts_results AS (
            SELECT
                s.id,
                s.recording_id,
                s.speaker,
                s.content,
                s.start_ms,
                s.end_ms,
                ts_rank(to_tsvector('english', s.content),
                    plainto_tsquery('english', :query)) as fts_rank,
                ROW_NUMBER() OVER (ORDER BY ts_rank(
                    to_tsvector('english', s.content),
                    plainto_tsquery('english', :query)) DESC) as fts_rn
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
              AND to_tsvector('english', s.content) @@ plainto_tsquery('english', :query)
              {recording_filter}
        ),
        semantic_results AS (
            SELECT
                s.id,
                s.recording_id,
                s.speaker,
                s.content,
                s.start_ms,
                s.end_ms,
                1 - (s.embedding <=> CAST(:embedding AS vector)) as semantic_score,
                ROW_NUMBER() OVER (ORDER BY s.embedding <=> CAST(:embedding AS vector)) as sem_rn
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
              AND s.embedding IS NOT NULL
              {recording_filter}
        ),
        combined AS (
            SELECT
                COALESCE(f.id, s.id) as id,
                COALESCE(f.recording_id, s.recording_id) as recording_id,
                COALESCE(f.speaker, s.speaker) as speaker,
                COALESCE(f.content, s.content) as content,
                COALESCE(f.start_ms, s.start_ms) as start_ms,
                COALESCE(f.end_ms, s.end_ms) as end_ms,
                COALESCE(1.0 / (60 + f.fts_rn), 0) + COALESCE(1.0 / (60 + s.sem_rn), 0) as rrf_score
            FROM fts_results f
            FULL OUTER JOIN semantic_results s ON f.id = s.id
        )
        SELECT
            c.id,
            c.recording_id,
            c.speaker,
            c.content,
            c.start_ms,
            c.end_ms,
            c.rrf_score,
            r.title as recording_title
        FROM combined c
        JOIN recordings r ON c.recording_id = r.id AND r.deleted_at IS NULL
        ORDER BY c.rrf_score DESC
        LIMIT :limit
    """.replace("{recording_filter}", recording_filter))

    params: dict = {
        "query": question,
        "user_id": str(user_id),
        "embedding": query_embedding,
        "limit": limit,
    }
    if recording_ids:
        params["recording_ids"] = [str(rid) for rid in recording_ids]

    result = await db.execute(hybrid_query, params)
    rows = result.fetchall()
    logger.info(
        "retrieve_context query=%s results=%d",
        safe_text_digest(question, label="query"),
        len(rows),
    )
    return rows


def build_context_text(rows: list) -> str:
    """Format retrieved segments into a context block."""
    if not rows:
        return "No relevant transcript segments found."

    parts = []
    for row in rows:
        speaker = row.speaker or "Unknown"
        title = row.recording_title or "Untitled"
        parts.append(f"[Recording: {title}] [{speaker}]: {row.content}")

    return "\n\n".join(parts)
