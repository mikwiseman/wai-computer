"""Wai Companion REST routes — CRUD plus SSE message streaming."""

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from app.api.deps import CurrentUser, Database
from app.core.companion import CompanionError, ErrorEvent, run_turn
from app.models.companion import ChatMessage, Conversation, MessageCitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])


CONVERSATIONS_DEFAULT_LIMIT = 50
CONVERSATIONS_MAX_LIMIT = 200
MESSAGES_DEFAULT_LIMIT = 50
MESSAGES_MAX_LIMIT = 500


class ConversationScope(BaseModel):
    """Filter applied to retrieval for every turn of this conversation."""

    recording_ids: list[str] | None = None
    folder_ids: list[str] | None = None
    types: list[str] | None = None
    speakers: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class CreateConversationRequest(BaseModel):
    scope: ConversationScope | None = None


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    scope: ConversationScope | None = None
    pinned: bool | None = None
    archived: bool | None = None


class CitationResponse(BaseModel):
    id: str
    segment_id: str | None
    recording_id: str | None
    span_start: int
    span_end: int
    citation_index: int


class MessageResponse(BaseModel):
    id: str
    role: str
    content: Any
    tool_calls: list[Any] | None
    citations: list[CitationResponse]
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    scope: dict[str, Any] | None
    pinned_at: datetime | None
    last_message_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageResponse]


class ConversationList(BaseModel):
    chats: list[ConversationSummary]


def _scope_to_jsonb(scope: ConversationScope | None) -> dict[str, Any] | None:
    if scope is None:
        return None
    return scope.model_dump(mode="json", exclude_none=True)


def _to_summary(c: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=str(c.id),
        title=c.title,
        scope=c.scope,
        pinned_at=c.pinned_at,
        last_message_at=c.last_message_at,
        archived_at=c.archived_at,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _to_message(m: ChatMessage) -> MessageResponse:
    return MessageResponse(
        id=str(m.id),
        role=m.role,
        content=m.content,
        tool_calls=m.tool_calls,
        citations=[
            CitationResponse(
                id=str(cit.id),
                segment_id=str(cit.segment_id) if cit.segment_id else None,
                recording_id=str(cit.recording_id) if cit.recording_id else None,
                span_start=cit.span_start,
                span_end=cit.span_end,
                citation_index=cit.citation_index,
            )
            for cit in m.citations
        ],
        model=m.model,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        cached_tokens=m.cached_tokens,
        latency_ms=m.latency_ms,
        created_at=m.created_at,
    )


async def _load_user_chat(
    db, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            and_(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return chat


@router.post(
    "/chats", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED
)
async def create_chat(
    request: CreateConversationRequest,
    user: CurrentUser,
    db: Database,
) -> ConversationSummary:
    chat = Conversation(
        user_id=user.id,
        scope=_scope_to_jsonb(request.scope),
    )
    db.add(chat)
    await db.flush()
    await db.refresh(chat)
    logger.info("companion chat created user_id=%s chat_id=%s", user.id, chat.id)
    return _to_summary(chat)


@router.get("/chats", response_model=ConversationList)
async def list_chats(
    user: CurrentUser,
    db: Database,
    limit: int = Query(
        CONVERSATIONS_DEFAULT_LIMIT, ge=1, le=CONVERSATIONS_MAX_LIMIT
    ),
    before: str | None = Query(
        None,
        description=(
            "Cursor: id of the last conversation from the previous page. "
            "Returns conversations with last_message_at strictly older than that one."
        ),
    ),
) -> ConversationList:
    stmt = select(Conversation).where(
        and_(
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
    )

    if before is not None:
        try:
            before_uuid = uuid.UUID(before)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid cursor: {exc}",
            ) from exc
        cursor_result = await db.execute(
            select(Conversation.last_message_at, Conversation.created_at).where(
                and_(
                    Conversation.id == before_uuid,
                    Conversation.user_id == user.id,
                )
            )
        )
        cursor_row = cursor_result.one_or_none()
        if cursor_row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cursor does not match an existing conversation",
            )
        # Order key: COALESCE(last_message_at, created_at) DESC. Cursor pages
        # forward by including rows strictly older than the cursor's key.
        cursor_key = cursor_row[0] if cursor_row[0] is not None else cursor_row[1]
        stmt = stmt.where(
            sa_coalesce_last_message_or_created() < cursor_key
        )

    stmt = stmt.order_by(
        sa_coalesce_last_message_or_created().desc()
    ).limit(limit)

    result = await db.execute(stmt)
    chats = list(result.scalars().all())
    return ConversationList(chats=[_to_summary(c) for c in chats])


@router.get("/chats/{chat_id}", response_model=ConversationDetail)
async def get_chat(
    chat_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
    messages_limit: int = Query(
        MESSAGES_DEFAULT_LIMIT, ge=1, le=MESSAGES_MAX_LIMIT
    ),
    before_message_id: str | None = Query(
        None,
        description=(
            "Cursor: id of the oldest message on the current page. "
            "Returns messages strictly older than that one."
        ),
    ),
) -> ConversationDetail:
    chat = await _load_user_chat(db, user.id, chat_id)

    msg_stmt = select(ChatMessage).where(ChatMessage.conversation_id == chat.id)

    if before_message_id is not None:
        try:
            before_uuid = uuid.UUID(before_message_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid cursor: {exc}",
            ) from exc
        cursor_result = await db.execute(
            select(ChatMessage.created_at).where(
                and_(
                    ChatMessage.id == before_uuid,
                    ChatMessage.conversation_id == chat.id,
                )
            )
        )
        cursor_created_at = cursor_result.scalar_one_or_none()
        if cursor_created_at is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cursor does not match an existing message in this chat",
            )
        msg_stmt = msg_stmt.where(ChatMessage.created_at < cursor_created_at)

    msg_stmt = msg_stmt.order_by(ChatMessage.created_at.desc()).limit(messages_limit)
    msg_result = await db.execute(msg_stmt)
    messages_desc = list(msg_result.scalars().all())

    # Preload citations for each message to avoid N+1.
    if messages_desc:
        cit_stmt = (
            select(MessageCitation)
            .where(
                MessageCitation.message_id.in_([m.id for m in messages_desc])
            )
            .order_by(MessageCitation.citation_index)
        )
        cit_result = await db.execute(cit_stmt)
        citations = list(cit_result.scalars().all())
        citations_by_msg: dict[uuid.UUID, list[MessageCitation]] = {}
        for cit in citations:
            citations_by_msg.setdefault(cit.message_id, []).append(cit)
        for m in messages_desc:
            m.citations = citations_by_msg.get(m.id, [])

    # Return messages oldest-first within the page so clients can append top.
    messages_asc = list(reversed(messages_desc))

    return ConversationDetail(
        **_to_summary(chat).model_dump(),
        messages=[_to_message(m) for m in messages_asc],
    )


@router.patch("/chats/{chat_id}", response_model=ConversationSummary)
async def update_chat(
    chat_id: uuid.UUID,
    request: UpdateConversationRequest,
    user: CurrentUser,
    db: Database,
) -> ConversationSummary:
    chat = await _load_user_chat(db, user.id, chat_id)

    if request.title is not None:
        chat.title = request.title
    if request.scope is not None:
        chat.scope = _scope_to_jsonb(request.scope)
    if request.pinned is not None:
        chat.pinned_at = datetime.now(timezone.utc) if request.pinned else None
    if request.archived is not None:
        chat.archived_at = datetime.now(timezone.utc) if request.archived else None

    await db.flush()
    await db.refresh(chat)
    return _to_summary(chat)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    chat = await _load_user_chat(db, user.id, chat_id)
    chat.deleted_at = datetime.now(timezone.utc)
    await db.flush()


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1)


def _sse_format(event_obj: Any) -> bytes:
    """Serialize a CompanionEvent dataclass as a single SSE frame."""
    data = asdict(event_obj)
    event_type = data.pop("type")
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@router.post("/chats/{chat_id}/messages")
async def post_message(
    chat_id: uuid.UUID,
    request: PostMessageRequest,
    user: CurrentUser,
    db: Database,
) -> StreamingResponse:
    # Load + ownership check up front so 404 / 401 are not buried inside SSE.
    await _load_user_chat(db, user.id, chat_id)

    async def event_stream():
        try:
            async for evt in run_turn(db, user.id, chat_id, request.content):
                yield _sse_format(evt)
        except CompanionError as exc:
            logger.warning(
                "companion turn error code=%s chat_id=%s", exc.code, chat_id
            )
            yield _sse_format(ErrorEvent(code=exc.code, message=exc.message))
        except Exception:
            logger.exception("companion turn unhandled error chat_id=%s", chat_id)
            yield _sse_format(
                ErrorEvent(code="internal_error", message="Turn failed")
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def sa_coalesce_last_message_or_created():
    """Use COALESCE(last_message_at, created_at) so brand-new chats sort by
    their creation time and only move once they have a real message."""
    from sqlalchemy import func

    return func.coalesce(Conversation.last_message_at, Conversation.created_at)
