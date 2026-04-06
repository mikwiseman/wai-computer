"""Search routes for hybrid (FTS + semantic) search."""

import logging

import sentry_sdk
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import CurrentUser, Database
from app.core.embeddings import format_embedding, generate_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

HYBRID_SEMANTIC_THRESHOLD = 0.3


class SearchResultResponse(BaseModel):
    """Response for a search result."""

    recording_id: str
    recording_title: str | None
    recording_type: str
    segment_id: str
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None
    score: float


class SearchResponse(BaseModel):
    """Response containing search results."""

    results: list[SearchResultResponse]
    total: int


@router.get("", response_model=SearchResponse)
async def hybrid_search(
    user: CurrentUser,
    db: Database,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    """
    Hybrid search combining full-text search (FTS) and semantic search.

    Uses RRF (Reciprocal Rank Fusion) to combine results from both methods.
    """
    logger.info("hybrid_search user_id=%s query=%r", user.id, q[:80])
    sentry_sdk.add_breadcrumb(
        category="search",
        message="Hybrid search",
        data={"query_length": len(q), "limit": limit, "offset": offset},
        level="info",
    )
    # Generate embedding for semantic search
    query_embedding_list = await generate_embedding(q)
    query_embedding = format_embedding(query_embedding_list)

    # Build hybrid search query using RRF
    # This combines FTS ranking with vector similarity
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
              AND 1 - (s.embedding <=> CAST(:embedding AS vector)) > :semantic_threshold
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
            r.title as recording_title,
            r.type as recording_type
        FROM combined c
        JOIN recordings r ON c.recording_id = r.id AND r.deleted_at IS NULL
        ORDER BY c.rrf_score DESC
        LIMIT :limit OFFSET :offset
    """)

    result = await db.execute(
        hybrid_query,
        {
            "query": q,
            "user_id": str(user.id),
            "embedding": query_embedding,
            "limit": limit,
            "offset": offset,
            "semantic_threshold": HYBRID_SEMANTIC_THRESHOLD,
        },
    )
    rows = result.fetchall()

    # Get total count using the same combined CTE logic
    count_query = text("""
        WITH fts_results AS (
            SELECT s.id
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
              AND to_tsvector('english', s.content) @@ plainto_tsquery('english', :query)
        ),
        semantic_results AS (
            SELECT s.id
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
              AND s.embedding IS NOT NULL
              AND 1 - (s.embedding <=> CAST(:embedding AS vector)) > :semantic_threshold
        )
        SELECT COUNT(DISTINCT COALESCE(f.id, s.id))
        FROM fts_results f
        FULL OUTER JOIN semantic_results s ON f.id = s.id
    """)

    count_result = await db.execute(
        count_query,
        {
            "query": q,
            "user_id": str(user.id),
            "embedding": query_embedding,
            "semantic_threshold": HYBRID_SEMANTIC_THRESHOLD,
        },
    )
    total = count_result.scalar() or 0

    return SearchResponse(
        results=[
            SearchResultResponse(
                recording_id=str(row.recording_id),
                recording_title=row.recording_title,
                recording_type=row.recording_type,
                segment_id=str(row.id),
                speaker=row.speaker,
                content=row.content,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                score=float(row.rrf_score),
            )
            for row in rows
        ],
        total=total,
    )


@router.get("/semantic", response_model=SearchResponse)
async def semantic_search(
    user: CurrentUser,
    db: Database,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    threshold: float = Query(0.3, ge=0, le=1, description="Minimum similarity threshold"),
) -> SearchResponse:
    """
    Pure semantic search using vector similarity.

    Returns segments with embeddings similar to the query.
    """
    logger.info("semantic_search user_id=%s query=%r", user.id, q[:80])
    sentry_sdk.add_breadcrumb(
        category="search",
        message="Semantic search",
        data={"query_length": len(q), "limit": limit, "threshold": threshold},
        level="info",
    )
    query_embedding_list = await generate_embedding(q)
    query_embedding = format_embedding(query_embedding_list)

    # Semantic search query
    query = text("""
        SELECT
            s.id,
            s.recording_id,
            s.speaker,
            s.content,
            s.start_ms,
            s.end_ms,
            1 - (s.embedding <=> CAST(:embedding AS vector)) as similarity,
            r.title as recording_title,
            r.type as recording_type
        FROM segments s
        JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :user_id
          AND r.deleted_at IS NULL
          AND s.embedding IS NOT NULL
          AND 1 - (s.embedding <=> CAST(:embedding AS vector)) > :threshold
        ORDER BY s.embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)

    result = await db.execute(
        query,
        {
            "embedding": query_embedding,
            "user_id": str(user.id),
            "threshold": threshold,
            "limit": limit,
        },
    )
    rows = result.fetchall()

    count_query = text("""
        SELECT COUNT(*)
        FROM segments s
        JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :user_id
          AND r.deleted_at IS NULL
          AND s.embedding IS NOT NULL
          AND 1 - (s.embedding <=> CAST(:embedding AS vector)) > :threshold
    """)
    count_result = await db.execute(
        count_query,
        {"embedding": query_embedding, "user_id": str(user.id), "threshold": threshold},
    )
    total = count_result.scalar() or 0

    return SearchResponse(
        results=[
            SearchResultResponse(
                recording_id=str(row.recording_id),
                recording_title=row.recording_title,
                recording_type=row.recording_type,
                segment_id=str(row.id),
                speaker=row.speaker,
                content=row.content,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                score=float(row.similarity),
            )
            for row in rows
        ],
        total=total,
    )


@router.get("/fts", response_model=SearchResponse)
async def fulltext_search(
    user: CurrentUser,
    db: Database,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    """
    Pure full-text search using PostgreSQL FTS.
    """
    logger.info("fulltext_search user_id=%s query=%r", user.id, q[:80])
    sentry_sdk.add_breadcrumb(
        category="search",
        message="Fulltext search",
        data={"query_length": len(q), "limit": limit, "offset": offset},
        level="info",
    )
    query = text("""
        SELECT
            s.id,
            s.recording_id,
            s.speaker,
            s.content,
            s.start_ms,
            s.end_ms,
            ts_rank(to_tsvector('english', s.content), plainto_tsquery('english', :query)) as rank,
            r.title as recording_title,
            r.type as recording_type
        FROM segments s
        JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :user_id
          AND r.deleted_at IS NULL
          AND to_tsvector('english', s.content) @@ plainto_tsquery('english', :query)
        ORDER BY rank DESC
        LIMIT :limit OFFSET :offset
    """)

    result = await db.execute(
        query,
        {"query": q, "user_id": str(user.id), "limit": limit, "offset": offset},
    )
    rows = result.fetchall()

    # Count total
    count_query = text("""
        SELECT COUNT(*)
        FROM segments s
        JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :user_id
          AND r.deleted_at IS NULL
          AND to_tsvector('english', s.content) @@ plainto_tsquery('english', :query)
    """)
    count_result = await db.execute(count_query, {"query": q, "user_id": str(user.id)})
    total = count_result.scalar() or 0

    return SearchResponse(
        results=[
            SearchResultResponse(
                recording_id=str(row.recording_id),
                recording_title=row.recording_title,
                recording_type=row.recording_type,
                segment_id=str(row.id),
                speaker=row.speaker,
                content=row.content,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                score=float(row.rank),
            )
            for row in rows
        ],
        total=total,
    )
