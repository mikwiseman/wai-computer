"""Search routes for hybrid (FTS + semantic) search."""

import logging
from time import perf_counter

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import CurrentUser, Database
from app.core.embeddings import format_embedding, generate_embedding
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    safe_query_metadata,
    safe_text_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

HYBRID_SEMANTIC_THRESHOLD = 0.3
SEARCH_SLOW_THRESHOLD_MS = 5_000


def _escape_like_term(value: str) -> str:
    """Escape user text used inside parameterized ILIKE patterns."""
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


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
    started_at = perf_counter()
    logger.info(
        "hybrid_search query=%s limit=%s offset=%s",
        safe_text_digest(q, label="query"),
        limit,
        offset,
    )
    add_sentry_breadcrumb(
        category="search",
        message="Hybrid search",
        data={**safe_query_metadata(q), "limit": limit, "offset": offset},
    )
    like_query = f"%{_escape_like_term(q)}%"
    # Generate embedding for semantic search
    query_embedding_list = await generate_embedding(q)
    query_embedding = format_embedding(query_embedding_list)

    # Prefer direct lexical matches. Semantic-only rows are useful for broad conceptual
    # searches, but they should not dilute obvious exact-term searches.
    hybrid_query = text("""
        WITH search_scope AS (
            SELECT
                s.id,
                s.recording_id,
                COALESCE(p.display_name, s.raw_label, s.speaker) as speaker,
                s.content,
                s.start_ms,
                s.end_ms,
                s.embedding,
                r.title as recording_title,
                r.type as recording_type,
                COALESCE((
                    SELECT string_agg(alias.value, ' ')
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(p.aliases) = 'array' THEN p.aliases
                            ELSE '[]'::jsonb
                        END
                    ) AS alias(value)
                ), '') as person_aliases,
                concat_ws(
                    ' ',
                    s.content,
                    r.title,
                    s.speaker,
                    s.raw_label,
                    p.display_name,
                    COALESCE((
                        SELECT string_agg(alias.value, ' ')
                        FROM jsonb_array_elements_text(
                            CASE
                                WHEN jsonb_typeof(p.aliases) = 'array' THEN p.aliases
                                ELSE '[]'::jsonb
                            END
                        ) AS alias(value)
                    ), '')
                ) as search_document
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            LEFT JOIN people p ON s.person_id = p.id AND p.user_id = r.user_id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
        ),
        lexical_results AS (
            SELECT
                *,
                (
                    ts_rank(
                        to_tsvector('simple', search_document),
                        plainto_tsquery('simple', :query)
                    )
                    + CASE WHEN lower(speaker) = lower(:query) THEN 10 ELSE 0 END
                    + CASE WHEN speaker ILIKE :like_query ESCAPE '!' THEN 5 ELSE 0 END
                    + CASE WHEN person_aliases ILIKE :like_query ESCAPE '!' THEN 4 ELSE 0 END
                    + CASE WHEN recording_title ILIKE :like_query ESCAPE '!' THEN 2 ELSE 0 END
                    + CASE WHEN content ILIKE :like_query ESCAPE '!' THEN 1 ELSE 0 END
                ) as lexical_score
            FROM search_scope
            WHERE to_tsvector('simple', search_document) @@ plainto_tsquery('simple', :query)
               OR content ILIKE :like_query ESCAPE '!'
               OR recording_title ILIKE :like_query ESCAPE '!'
               OR speaker ILIKE :like_query ESCAPE '!'
               OR person_aliases ILIKE :like_query ESCAPE '!'
        ),
        lexical_count AS (
            SELECT COUNT(*) as total FROM lexical_results
        ),
        semantic_results AS (
            SELECT
                id,
                recording_id,
                speaker,
                content,
                start_ms,
                end_ms,
                recording_title,
                recording_type,
                1 - (embedding <=> CAST(:embedding AS vector)) as score
            FROM search_scope
            WHERE (SELECT total FROM lexical_count) = 0
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> CAST(:embedding AS vector)) > :semantic_threshold
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :semantic_limit
        ),
        combined AS (
            SELECT
                id,
                recording_id,
                speaker,
                content,
                start_ms,
                end_ms,
                recording_title,
                recording_type,
                lexical_score as score
            FROM lexical_results
            UNION ALL
            SELECT
                id,
                recording_id,
                speaker,
                content,
                start_ms,
                end_ms,
                recording_title,
                recording_type,
                score
            FROM semantic_results
        )
        SELECT
            c.id,
            c.recording_id,
            c.speaker,
            c.content,
            c.start_ms,
            c.end_ms,
            c.score,
            c.recording_title,
            c.recording_type
        FROM combined c
        ORDER BY c.score DESC
        LIMIT :limit OFFSET :offset
    """)

    result = await db.execute(
        hybrid_query,
        {
            "query": q,
            "like_query": like_query,
            "user_id": str(user.id),
            "embedding": query_embedding,
            "limit": limit,
            "offset": offset,
            "semantic_limit": limit + offset,
            "semantic_threshold": HYBRID_SEMANTIC_THRESHOLD,
        },
    )
    rows = result.fetchall()

    # Get total count using the same combined CTE logic
    count_query = text("""
        WITH search_scope AS (
            SELECT
                s.id,
                s.embedding,
                s.content,
                r.title as recording_title,
                COALESCE(p.display_name, s.raw_label, s.speaker) as speaker,
                COALESCE((
                    SELECT string_agg(alias.value, ' ')
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(p.aliases) = 'array' THEN p.aliases
                            ELSE '[]'::jsonb
                        END
                    ) AS alias(value)
                ), '') as person_aliases,
                concat_ws(
                    ' ',
                    s.content,
                    r.title,
                    s.speaker,
                    s.raw_label,
                    p.display_name,
                    COALESCE((
                        SELECT string_agg(alias.value, ' ')
                        FROM jsonb_array_elements_text(
                            CASE
                                WHEN jsonb_typeof(p.aliases) = 'array' THEN p.aliases
                                ELSE '[]'::jsonb
                            END
                        ) AS alias(value)
                    ), '')
                ) as search_document
            FROM segments s
            JOIN recordings r ON s.recording_id = r.id
            LEFT JOIN people p ON s.person_id = p.id AND p.user_id = r.user_id
            WHERE r.user_id = :user_id
              AND r.deleted_at IS NULL
        ),
        lexical_results AS (
            SELECT id
            FROM search_scope
            WHERE to_tsvector('simple', search_document) @@ plainto_tsquery('simple', :query)
               OR content ILIKE :like_query ESCAPE '!'
               OR recording_title ILIKE :like_query ESCAPE '!'
               OR speaker ILIKE :like_query ESCAPE '!'
               OR person_aliases ILIKE :like_query ESCAPE '!'
        ),
        lexical_count AS (
            SELECT COUNT(*) as total FROM lexical_results
        ),
        semantic_results AS (
            SELECT id
            FROM search_scope
            WHERE (SELECT total FROM lexical_count) = 0
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> CAST(:embedding AS vector)) > :semantic_threshold
        )
        SELECT
            CASE
                WHEN (SELECT total FROM lexical_count) > 0
                THEN (SELECT total FROM lexical_count)
                ELSE (SELECT COUNT(*) FROM semantic_results)
            END
    """)

    count_result = await db.execute(
        count_query,
        {
            "query": q,
            "like_query": like_query,
            "user_id": str(user.id),
            "embedding": query_embedding,
            "semantic_threshold": HYBRID_SEMANTIC_THRESHOLD,
        },
    )
    total = count_result.scalar() or 0
    latency_ms = round((perf_counter() - started_at) * 1000)
    completion_data = {
        **safe_query_metadata(q),
        "limit": limit,
        "offset": offset,
        "latency_ms": latency_ms,
        "result_count": len(rows),
        "total": total,
    }
    add_sentry_breadcrumb(
        category="search",
        message="Hybrid search completed",
        data=completion_data,
    )
    if latency_ms >= SEARCH_SLOW_THRESHOLD_MS:
        capture_sentry_anomaly(
            "search.query.slow",
            "Search query latency exceeded threshold",
            category="search",
            extras={**completion_data, "slow_threshold_ms": SEARCH_SLOW_THRESHOLD_MS},
        )

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
                score=float(row.score),
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
    logger.info(
        "semantic_search query=%s limit=%s threshold=%s",
        safe_text_digest(q, label="query"),
        limit,
        threshold,
    )
    add_sentry_breadcrumb(
        category="search",
        message="Semantic search",
        data={**safe_query_metadata(q), "limit": limit, "threshold": threshold},
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
    logger.info(
        "fulltext_search query=%s limit=%s offset=%s",
        safe_text_digest(q, label="query"),
        limit,
        offset,
    )
    add_sentry_breadcrumb(
        category="search",
        message="Fulltext search",
        data={**safe_query_metadata(q), "limit": limit, "offset": offset},
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
