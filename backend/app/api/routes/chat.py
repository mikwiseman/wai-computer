"""Chat routes for conversational RAG Q&A against recordings."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Database
from app.core.chat import ChatResult, chat_with_recordings
from app.models.chat import ChatMessage, ChatSession

router = APIRouter(prefix="/chat", tags=["chat"])


# --- Request/Response schemas ---


class ChatRequest(BaseModel):
    """Request to send a chat question."""

    question: str = Field(min_length=1)
    session_id: str | None = None
    recording_ids: list[str] | None = None


class SourceResponse(BaseModel):
    """A source segment in the chat response."""

    segment_id: str
    recording_id: str
    recording_title: str | None
    speaker: str | None
    content: str
    start_ms: int | None
    end_ms: int | None


class ChatResponse(BaseModel):
    """Response from the chat endpoint."""

    answer: str
    session_id: str
    message_id: str
    sources: list[SourceResponse]


class ChatSessionListItem(BaseModel):
    """A chat session in a list response."""

    id: str
    title: str | None
    recording_ids: list | None
    created_at: str
    message_count: int


class ChatMessageResponse(BaseModel):
    """A message in a chat session."""

    id: str
    role: str
    content: str
    source_segment_ids: list | None
    source_recording_ids: list | None
    created_at: str


class ChatSessionDetailResponse(BaseModel):
    """Full chat session with messages."""

    id: str
    title: str | None
    recording_ids: list | None
    created_at: str
    messages: list[ChatMessageResponse]


# --- Endpoints ---


@router.post("", response_model=ChatResponse)
async def send_chat_message(
    request: ChatRequest,
    user: CurrentUser,
    db: Database,
) -> ChatResponse:
    """Send a question and get a RAG-powered answer from meeting transcripts."""
    try:
        session_id = uuid.UUID(request.session_id) if request.session_id else None
        recording_ids = (
            [uuid.UUID(rid) for rid in request.recording_ids]
            if request.recording_ids
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID: {exc}",
        ) from exc

    result: ChatResult = await chat_with_recordings(
        db=db,
        user_id=user.id,
        question=request.question,
        session_id=session_id,
        recording_ids=recording_ids,
    )

    return ChatResponse(
        answer=result.answer,
        session_id=result.session_id,
        message_id=result.message_id,
        sources=[
            SourceResponse(
                segment_id=s.segment_id,
                recording_id=s.recording_id,
                recording_title=s.recording_title,
                speaker=s.speaker,
                content=s.content,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
            )
            for s in result.source_segments
        ],
    )


@router.get("/sessions", response_model=list[ChatSessionListItem])
async def list_chat_sessions(
    user: CurrentUser,
    db: Database,
) -> list[ChatSessionListItem]:
    """List all chat sessions for the current user, most recent first."""
    # Query sessions with message counts
    stmt = (
        select(
            ChatSession,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.created_at.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        ChatSessionListItem(
            id=str(session.id),
            title=session.title,
            recording_ids=session.recording_ids,
            created_at=session.created_at.isoformat(),
            message_count=message_count,
        )
        for session, message_count in rows
    ]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> ChatSessionDetailResponse:
    """Get a chat session with all its messages."""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    # Load messages
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = msg_result.scalars().all()

    return ChatSessionDetailResponse(
        id=str(session.id),
        title=session.title,
        recording_ids=session.recording_ids,
        created_at=session.created_at.isoformat(),
        messages=[
            ChatMessageResponse(
                id=str(msg.id),
                role=msg.role,
                content=msg.content,
                source_segment_ids=msg.source_segment_ids,
                source_recording_ids=msg.source_recording_ids,
                created_at=msg.created_at.isoformat(),
            )
            for msg in messages
        ],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Delete a chat session and all its messages."""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    await db.delete(session)
    await db.flush()
