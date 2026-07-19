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
from app.core.vector_search import configure_vector_search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

HYBRID_SEMANTIC_THRESHOLD = 0.3
SEARCH_SLOW_THRESHOLD_MS = 5_000

# Shared CTE for the hybrid search's lexical phase: the user's segments joined
# with recording + person context, matched via cross-field FTS (so multi-word
# queries can span content/title/speaker/aliases) plus substring ILIKEs.
# Deliberately excludes s.embedding — the lexical phase must never read 6 KB
# vectors off disk. Params: :user_id, :query, :like_query.
_HYBRID_LEXICAL_CTE_SQL = """
        search_scope AS (
            SELECT
                s.id,
                s.recording_id,
                COALESCE(p.display_name, s.raw_label, s.speaker) as speaker,
                s.content,
                s.start_ms,
                s.end_ms,
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
                        to_tsvector('russian', lower(search_document COLLATE "und-x-icu")),
                        plainto_tsquery('russian', lower(:query COLLATE "und-x-icu"))
                    )
                    + CASE WHEN lower(speaker) = lower(:query) THEN 10 ELSE 0 END
                    + CASE WHEN speaker ILIKE :like_query ESCAPE '!' THEN 5 ELSE 0 END
                    + CASE WHEN person_aliases ILIKE :like_query ESCAPE '!' THEN 4 ELSE 0 END
                    + CASE WHEN recording_title ILIKE :like_query ESCAPE '!' THEN 2 ELSE 0 END
                    + CASE WHEN content ILIKE :like_query ESCAPE '!' THEN 1 ELSE 0 END
                ) as lexical_score
            FROM search_scope
            WHERE to_tsvector('russian', lower(search_document COLLATE "und-x-icu"))
                @@ plainto_tsquery('russian', lower(:query COLLATE "und-x-icu"))
               OR content ILIKE :like_query ESCAPE '!'
               OR recording_title ILIKE :like_query ESCAPE '!'
               OR speaker ILIKE :like_query ESCAPE '!'
               OR person_aliases ILIKE :like_query ESCAPE '!'
        )
"""


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


class UnifiedHitResponse(BaseModel):
    """One hit in the unified (recordings + items) search."""

    source_kind: str  # "recording" | "item"
    parent_id: str
    chunk_id: str
    title: str | None
    kind: str
    snippet: str
    score: float
    created_at: str | None


class UnifiedSearchResponse(BaseModel):
    results: list[UnifiedHitResponse]
    total: int


@router.get("/all", response_model=UnifiedSearchResponse)
async def unified_search_route(
    user: CurrentUser,
    db: Database,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> UnifiedSearchResponse:
    """Search everything — recordings AND items — fused with RRF + recency.

    This powers the unified feed's "search everything" box. Results carry a
    ``source_kind`` ("recording" | "item") so the client can route a click to
    the right detail view.
    """
    from app.core.unified_search import unified_search

    started_at = perf_counter()
    logger.info("unified_search query=%s limit=%s", safe_text_digest(q, label="query"), limit)
    add_sentry_breadcrumb(
        category="search",
        message="Unified search",
        data={**safe_query_metadata(q), "limit": limit},
    )
    hits = await unified_search(db, user.id, q, limit=limit, per_parent_limit=1)
    latency_ms = round((perf_counter() - started_at) * 1000)
    if latency_ms >= SEARCH_SLOW_THRESHOLD_MS:
        capture_sentry_anomaly(
            "search.unified.slow",
            "Unified search latency exceeded threshold",
            category="search",
            extras={**safe_query_metadata(q), "latency_ms": latency_ms},
        )
    return UnifiedSearchResponse(
        results=[
            UnifiedHitResponse(
                source_kind=h.source_kind,
                parent_id=h.parent_id,
                chunk_id=h.chunk_id,
                title=h.title,
                kind=h.kind,
                snippet=h.snippet,
                score=h.score,
                created_at=h.created_at,
            )
            for h in hits
        ],
        total=len(hits),
    )


@router.get("", response_model=SearchResponse)
async def hybrid_search(
    user: CurrentUser,
    db: Database,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    """
    Hybrid search: lexical matches first, semantic fallback when none exist.

    Two-phase for speed on big accounts: the lexical page (with its total via
    a window count) runs in ONE scan and needs no query embedding, so exact
    term searches skip the embedding-provider round-trip entirely. Only a
    zero-lexical-hit query pays for the embedding + vector scan.
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

    lexical_page_query = text(f"""
        WITH {_HYBRID_LEXICAL_CTE_SQL}
        SELECT
            l.id,
            l.recording_id,
            l.speaker,
            l.content,
            l.start_ms,
            l.end_ms,
            l.lexical_score as score,
            l.recording_title,
            l.recording_type,
            (SELECT COUNT(*) FROM lexical_results) as total
        FROM lexical_results l
        ORDER BY l.lexical_score DESC
        LIMIT :limit OFFSET :offset
    """)

    lexical_params = {
        "query": q,
        "like_query": like_query,
        "user_id": str(user.id),
    }
    result = await db.execute(
        lexical_page_query, {**lexical_params, "limit": limit, "offset": offset}
    )
    rows = result.fetchall()
    if rows:
        total = int(rows[0].total)
    else:
        # Empty page (offset past the end, or no hits at all): the window
        # count came back with no row, so ask for the total explicitly.
        count_result = await db.execute(
            text(f"WITH {_HYBRID_LEXICAL_CTE_SQL} SELECT COUNT(*) FROM lexical_results"),
            lexical_params,
        )
        total = count_result.scalar() or 0

    if total == 0:
        # No lexical hits anywhere — fall back to semantic search. Only now is
        # the query embedding worth its provider round-trip.
        query_embedding = format_embedding(await generate_embedding(q))
        await configure_vector_search(db)
        semantic_query = text("""
            WITH semantic_results AS (
                SELECT
                    s.id,
                    s.recording_id,
                    COALESCE(p.display_name, s.raw_label, s.speaker) as speaker,
                    s.content,
                    s.start_ms,
                    s.end_ms,
                    r.title as recording_title,
                    r.type as recording_type,
                    1 - (s.embedding <=> CAST(:embedding AS vector)) as score
                FROM segments s
                JOIN recordings r ON s.recording_id = r.id
                LEFT JOIN people p ON s.person_id = p.id AND p.user_id = r.user_id
                WHERE r.user_id = :user_id
                  AND r.deleted_at IS NULL
                  AND s.embedding IS NOT NULL
                  AND 1 - (s.embedding <=> CAST(:embedding AS vector)) > :semantic_threshold
            )
            SELECT
                s.*,
                (SELECT COUNT(*) FROM semantic_results) as total
            FROM semantic_results s
            ORDER BY s.score DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await db.execute(
            semantic_query,
            {
                "user_id": str(user.id),
                "embedding": query_embedding,
                "semantic_threshold": HYBRID_SEMANTIC_THRESHOLD,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.fetchall()
        total = int(rows[0].total) if rows else 0
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
    await configure_vector_search(db)

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
            ts_rank(
                to_tsvector('russian', lower(s.content COLLATE "und-x-icu")),
                plainto_tsquery('russian', lower(:query COLLATE "und-x-icu"))
            ) as rank,
            r.title as recording_title,
            r.type as recording_type
        FROM segments s
        JOIN recordings r ON s.recording_id = r.id
        WHERE r.user_id = :user_id
          AND r.deleted_at IS NULL
          AND to_tsvector('russian', lower(s.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:query COLLATE "und-x-icu"))
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
          AND to_tsvector('russian', lower(s.content COLLATE "und-x-icu"))
              @@ plainto_tsquery('russian', lower(:query COLLATE "und-x-icu"))
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
