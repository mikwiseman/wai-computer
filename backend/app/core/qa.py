"""Stateless RAG QA pipeline against recordings (legacy /api/qa route).

Retained until the web client migrates from GlobalQAPanel to the streaming
Companion endpoint, then deleted in phase 9.
"""

import logging
import uuid
from dataclasses import dataclass, field

import openai
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embeddings import format_embedding, generate_embedding
from app.core.observability import safe_text_digest
from app.core.openai_client import get_openai_client

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPT = (
    "You are a helpful meeting assistant. Answer questions based on "
    "the provided meeting transcript context. "
    "If the context doesn't contain enough information to answer, "
    "say so clearly. "
    "Always reference specific details from the transcripts "
    "when possible."
)


@dataclass
class SourceSegment:
    """A source segment returned with the QA response."""

    segment_id: str
    recording_id: str
    recording_title: str | None
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None


@dataclass
class QAResult:
    """Result from the stateless QA pipeline."""

    answer: str
    source_segments: list[SourceSegment] = field(default_factory=list)


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
    """Format retrieved segments into a context block for the model."""
    if not rows:
        return "No relevant transcript segments found."

    parts = []
    for row in rows:
        speaker = row.speaker or "Unknown"
        title = row.recording_title or "Untitled"
        parts.append(f"[Recording: {title}] [{speaker}]: {row.content}")

    return "\n\n".join(parts)


async def ask_database(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    recording_ids: list[uuid.UUID] | None = None,
) -> QAResult:
    """Stateless single-shot QA pipeline.

    1. Hybrid retrieval over the user's segments.
    2. OpenAI Responses API call with the retrieved context.
    3. Return the answer plus the source segments.
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="QA service not configured",
        )

    logger.info(
        "ask_database question=%s",
        safe_text_digest(question, label="question"),
    )
    context_rows = await retrieve_context(db, user_id, question, recording_ids=recording_ids)
    context_text = build_context_text(context_rows)

    user_content = f"Context from meeting transcripts:\n\n{context_text}\n\nQuestion: {question}"

    client = get_openai_client()
    try:
        response = await client.responses.create(
            model=settings.openai_llm_model,
            instructions=SYSTEM_PROMPT,
            input=user_content,
            max_output_tokens=4096,
        )
    except openai.APIConnectionError:
        logger.error("qa OpenAI API connection error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to AI service",
        ) from None
    except openai.RateLimitError:
        logger.warning("qa OpenAI API rate limited")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service rate limit exceeded. Please try again later.",
        ) from None
    except openai.APIStatusError as exc:
        logger.error("qa OpenAI API error: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {exc.message}",
        ) from exc

    answer = response.output_text
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Empty response from AI service",
        )

    source_segments = [
        SourceSegment(
            segment_id=str(row.id),
            recording_id=str(row.recording_id),
            recording_title=row.recording_title,
            speaker=row.speaker,
            content=row.content,
            start_ms=row.start_ms,
            end_ms=row.end_ms,
        )
        for row in context_rows
    ]

    logger.info(
        "ask_database completed sources=%d answer_len=%d",
        len(source_segments), len(answer),
    )
    return QAResult(
        answer=answer,
        source_segments=source_segments,
    )
