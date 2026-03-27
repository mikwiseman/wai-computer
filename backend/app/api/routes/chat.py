"""Chat routes for conversational RAG Q&A against recordings."""

import uuid
from datetime import datetime, timezone

import sentry_sdk
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

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
    recording_ids: list[str] | None
    created_at: str
    message_count: int
    pinned_at: str | None = None


class ChatMessageResponse(BaseModel):
    """A message in a chat session."""

    id: str
    role: str
    content: str
    source_segment_ids: list[str] | None
    source_recording_ids: list[str] | None
    created_at: str


class ChatSessionDetailResponse(BaseModel):
    """Full chat session with messages."""

    id: str
    title: str | None
    recording_ids: list[str] | None
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
    sentry_sdk.add_breadcrumb(
        category="chat",
        message="Chat message sent",
        data={
            "session_id": request.session_id,
            "has_recording_filter": bool(request.recording_ids),
        },
        level="info",
    )
    try:
        session_id = uuid.UUID(request.session_id) if request.session_id else None
        recording_ids = (
            [uuid.UUID(rid) for rid in request.recording_ids]
            if request.recording_ids
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
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
    """List all chat sessions for the current user, pinned first then most recent."""
    sentry_sdk.add_breadcrumb(category="chat", message="List chat sessions", level="info")
    # Query sessions with message counts; pinned sessions come first
    stmt = (
        select(
            ChatSession,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user.id)
        .group_by(ChatSession.id)
        .order_by(
            case((ChatSession.pinned_at.is_not(None), 0), else_=1),
            ChatSession.pinned_at.desc().nulls_last(),
            ChatSession.created_at.desc(),
        )
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
            pinned_at=session.pinned_at.isoformat() if session.pinned_at else None,
        )
        for session, message_count in rows
    ]


@router.get("/sessions/search", response_model=list[ChatSessionListItem])
async def search_chat_sessions(
    user: CurrentUser,
    db: Database,
    q: str = Query(min_length=1),
) -> list[ChatSessionListItem]:
    """Search chat sessions by message content."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    matching_session_ids = (
        select(ChatMessage.session_id)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.user_id == user.id,
            ChatMessage.content.ilike(f"%{escaped}%", escape="\\"),
        )
        .distinct()
    )

    stmt = (
        select(
            ChatSession,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.id.in_(matching_session_ids))
        .group_by(ChatSession.id)
        .order_by(
            case((ChatSession.pinned_at.is_not(None), 0), else_=1),
            ChatSession.pinned_at.desc().nulls_last(),
            ChatSession.created_at.desc(),
        )
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
            pinned_at=session.pinned_at.isoformat() if session.pinned_at else None,
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


class RenameSessionRequest(BaseModel):
    """Request to rename a chat session."""

    title: str | None = Field(min_length=1)


class RenameSessionResponse(BaseModel):
    """Response after renaming a chat session."""

    id: str
    title: str | None


@router.patch("/sessions/{session_id}", response_model=RenameSessionResponse)
async def rename_chat_session(
    session_id: uuid.UUID,
    request: RenameSessionRequest,
    user: CurrentUser,
    db: Database,
) -> RenameSessionResponse:
    """Rename a chat session."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    session.title = request.title
    await db.flush()

    return RenameSessionResponse(id=str(session.id), title=session.title)


@router.get("/sessions/{session_id}/export")
async def export_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> Response:
    """Export a chat session as markdown."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = msg_result.scalars().all()

    title = session.title or "Chat Session"
    lines = [f"# {title}\n"]

    for msg in messages:
        label = "**You:**" if msg.role == "user" else "**Assistant:**"
        lines.append(f"{label}\n{msg.content}\n")

    markdown = "\n".join(lines)

    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="chat-{session_id}.md"',
        },
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Delete a chat session and all its messages."""
    sentry_sdk.add_breadcrumb(
        category="chat",
        message="Delete chat session",
        data={"session_id": str(session_id)},
        level="info",
    )
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


class PinSessionResponse(BaseModel):
    """Response after pinning/unpinning a chat session."""

    id: str
    pinned_at: str | None


@router.post(
    "/sessions/{session_id}/pin",
    response_model=PinSessionResponse,
)
async def pin_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> PinSessionResponse:
    """Pin a chat session so it appears at the top of the list."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    session.pinned_at = datetime.now(timezone.utc)
    await db.flush()

    return PinSessionResponse(
        id=str(session.id),
        pinned_at=session.pinned_at.isoformat(),
    )


@router.delete(
    "/sessions/{session_id}/pin",
    response_model=PinSessionResponse,
)
async def unpin_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> PinSessionResponse:
    """Unpin a chat session."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    session.pinned_at = None
    await db.flush()

    return PinSessionResponse(
        id=str(session.id),
        pinned_at=None,
    )
