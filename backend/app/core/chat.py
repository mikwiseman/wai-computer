"""RAG chat pipeline for conversational Q&A against recordings."""

import uuid
from dataclasses import dataclass, field

import anthropic
from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embeddings import generate_embedding
from app.models.chat import ChatMessage, ChatSession

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
    """A source segment returned with the chat response."""

    segment_id: str
    recording_id: str
    recording_title: str | None
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None


@dataclass
class ChatResult:
    """Result from the chat RAG pipeline."""

    answer: str
    session_id: str
    message_id: str
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
    query_embedding = "[" + ",".join(str(x) for x in query_embedding_list) + "]"

    recording_filter = ""
    if recording_ids:
        recording_filter = "AND s.recording_id = ANY(:recording_ids)"

    hybrid_query = text(f"""
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
    """)

    params: dict = {
        "query": question,
        "user_id": str(user_id),
        "embedding": query_embedding,
        "limit": limit,
    }
    if recording_ids:
        params["recording_ids"] = [str(rid) for rid in recording_ids]

    result = await db.execute(hybrid_query, params)
    return result.fetchall()


def build_context_text(rows: list) -> str:
    """Format retrieved segments into a context block for Claude."""
    if not rows:
        return "No relevant transcript segments found."

    parts = []
    for row in rows:
        speaker = row.speaker or "Unknown"
        title = row.recording_title or "Untitled"
        parts.append(f"[Recording: {title}] [{speaker}]: {row.content}")

    return "\n\n".join(parts)


async def chat_with_recordings(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID | None = None,
    recording_ids: list[uuid.UUID] | None = None,
) -> ChatResult:
    """
    Main RAG chat function.

    1. Gets or creates a ChatSession
    2. Retrieves context via hybrid search
    3. Loads conversation history (last 10 turns)
    4. Sends question + context + history to Claude
    5. Stores messages in the DB
    6. Returns the response with source info
    """
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service not configured",
        )

    # Get or create session
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found",
            )
    else:
        rec_ids = (
            [str(rid) for rid in recording_ids]
            if recording_ids
            else None
        )
        session = ChatSession(user_id=user_id, recording_ids=rec_ids)
        db.add(session)
        await db.flush()

    # Retrieve context
    context_rows = await retrieve_context(db, user_id, question, recording_ids=recording_ids)
    context_text = build_context_text(context_rows)

    # Load last 10 turns (20 messages) of conversation history
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(20)
    )
    history_messages = list(reversed(history_result.scalars().all()))

    # Build Claude messages
    messages: list[dict] = []

    # Add conversation history
    for msg in history_messages:
        messages.append({"role": msg.role, "content": msg.content})

    # Add new user question with context
    user_content = f"Context from meeting transcripts:\n\n{context_text}\n\nQuestion: {question}"
    messages.append({"role": "user", "content": user_content})

    # Call Claude
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        if not response.content:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Empty response from AI service",
            )
        answer = response.content[0].text
    except anthropic.APIConnectionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to AI service",
        )
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service rate limit exceeded. Please try again later.",
        )
    except anthropic.APIStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {e.message}",
        )

    # Build source segments
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

    source_segment_ids = [s.segment_id for s in source_segments]
    source_recording_ids = list({s.recording_id for s in source_segments})

    # Store user message
    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        content=question,
    )
    db.add(user_message)

    # Store assistant message
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        source_segment_ids=source_segment_ids,
        source_recording_ids=source_recording_ids,
    )
    db.add(assistant_message)
    await db.flush()

    # Auto-generate title from first question if session is new
    if not session.title:
        session.title = question[:500]
        await db.flush()

    return ChatResult(
        answer=answer,
        session_id=str(session.id),
        message_id=str(assistant_message.id),
        source_segments=source_segments,
    )
