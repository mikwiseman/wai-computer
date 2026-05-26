"""Wai Companion REST routes — CRUD plus SSE message streaming."""

import asyncio
import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from app.api.deps import CurrentUser, Database
from app.core.companion import CompanionError, ErrorEvent, TurnContext, run_turn
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    safe_query_metadata,
)
from app.models.companion import ChatMessage, Conversation, MessageCitation
from app.models.recording import Folder, Recording

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])


CONVERSATIONS_DEFAULT_LIMIT = 50
CONVERSATIONS_MAX_LIMIT = 200
MESSAGES_DEFAULT_LIMIT = 50
MESSAGES_MAX_LIMIT = 500
# Heartbeat must be shorter than the shortest reverse-proxy idle timeout in
# front of this service (Caddy default is 30s).
SSE_HEARTBEAT_SECONDS = 15.0
COMPANION_TURN_SLOW_THRESHOLD_MS = 30_000


class ConversationScope(BaseModel):
    """Filter applied to retrieval for every turn of this conversation.

    Only `recording_ids` is enforced server-side; accepting more fields here
    would silently fail at retrieval time, violating no-fallbacks.
    """

    recording_ids: list[str] | None = None


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


def _to_message(
    m: ChatMessage,
    citations: list[MessageCitation] | None = None,
) -> MessageResponse:
    cits = citations if citations is not None else []
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
            for cit in cits
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
    citations_by_msg: dict[uuid.UUID, list[MessageCitation]] = {}
    if messages_desc:
        cit_stmt = (
            select(MessageCitation)
            .where(
                MessageCitation.message_id.in_([m.id for m in messages_desc])
            )
            .order_by(MessageCitation.citation_index)
        )
        cit_result = await db.execute(cit_stmt)
        for cit in cit_result.scalars().all():
            citations_by_msg.setdefault(cit.message_id, []).append(cit)

    # Return messages oldest-first within the page so clients can append top.
    messages_asc = list(reversed(messages_desc))

    return ConversationDetail(
        **_to_summary(chat).model_dump(),
        messages=[
            _to_message(m, citations_by_msg.get(m.id, []))
            for m in messages_asc
        ],
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
    # Per-turn working memory the client knows and the server cannot guess:
    # local calendar date (the server only knows UTC), IANA timezone, and
    # the recording/folder the user has open in the UI right now. These let
    # the agent resolve "yesterday" / "вчера" / "this week" correctly and
    # answer questions about the recording the user is staring at without
    # naming it. Missing fields are surfaced to the model verbatim (no
    # silent UTC default) per AGENTS.md "no fallbacks".
    client_local_date: str | None = Field(default=None, max_length=10)
    client_timezone: str | None = Field(default=None, max_length=64)
    viewing_recording_id: uuid.UUID | None = None
    viewing_folder_id: uuid.UUID | None = None


def _sse_format(event_obj: Any) -> bytes:
    """Serialize a CompanionEvent dataclass as a single SSE frame."""
    data = asdict(event_obj)
    event_type = data.pop("type")
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


_SSE_HEARTBEAT = b": keep-alive\n\n"


async def _resolve_viewing_titles(
    db: Database,
    user_id: uuid.UUID,
    recording_id: uuid.UUID | None,
    folder_id: uuid.UUID | None,
) -> tuple[str | None, str | None]:
    """Look up the title of the recording and the name of the folder the
    client says the user is currently viewing. Both lookups are owner-scoped
    so a stale/forged id from another user cannot leak a title.
    """
    recording_title: str | None = None
    folder_name: str | None = None
    if recording_id is not None:
        result = await db.execute(
            select(Recording.title).where(
                Recording.id == recording_id,
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
        recording_title = result.scalar_one_or_none()
    if folder_id is not None:
        result = await db.execute(
            select(Folder.name).where(
                Folder.id == folder_id,
                Folder.user_id == user_id,
            )
        )
        folder_name = result.scalar_one_or_none()
    return recording_title, folder_name


@router.post("/chats/{chat_id}/messages")
async def post_message(
    chat_id: uuid.UUID,
    request: PostMessageRequest,
    user: CurrentUser,
    db: Database,
) -> StreamingResponse:
    # Load + ownership check up front so 404 / 401 are not buried inside SSE.
    await _load_user_chat(db, user.id, chat_id)
    message_meta = safe_query_metadata(request.content)
    add_sentry_breadcrumb(
        category="companion",
        message="Companion turn requested",
        data={
            "chat_id": str(chat_id),
            **message_meta,
            "has_viewing_recording": request.viewing_recording_id is not None,
            "has_viewing_folder": request.viewing_folder_id is not None,
        },
    )

    viewing_recording_title, viewing_folder_name = await _resolve_viewing_titles(
        db,
        user.id,
        request.viewing_recording_id,
        request.viewing_folder_id,
    )
    turn_context = TurnContext(
        client_local_date=request.client_local_date,
        client_timezone=request.client_timezone,
        viewing_recording_title=viewing_recording_title,
        viewing_folder_name=viewing_folder_name,
    )

    async def event_stream():
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        async def producer() -> None:
            started_at = perf_counter()
            event_count = 0
            failed = False
            try:
                async for evt in run_turn(
                    db,
                    user.id,
                    chat_id,
                    request.content,
                    turn_context=turn_context,
                ):
                    event_count += 1
                    await queue.put(_sse_format(evt))
            except CompanionError as exc:
                failed = True
                latency_ms = round((perf_counter() - started_at) * 1000)
                capture_sentry_anomaly(
                    "companion.turn.failed",
                    "Companion turn failed",
                    category="companion",
                    extras={
                        "chat_id": str(chat_id),
                        **message_meta,
                        "latency_ms": latency_ms,
                        "event_count": event_count,
                        "error_code": exc.code,
                    },
                )
                logger.warning(
                    "companion turn error code=%s chat_id=%s", exc.code, chat_id
                )
                await queue.put(
                    _sse_format(ErrorEvent(code=exc.code, message=exc.message))
                )
            except Exception as exc:
                failed = True
                latency_ms = round((perf_counter() - started_at) * 1000)
                capture_sentry_anomaly(
                    "companion.turn.failed",
                    "Companion turn failed unexpectedly",
                    category="companion",
                    extras={
                        "chat_id": str(chat_id),
                        **message_meta,
                        "latency_ms": latency_ms,
                        "event_count": event_count,
                        "error_type": type(exc).__name__,
                    },
                    level="error",
                )
                logger.exception(
                    "companion turn unhandled error chat_id=%s", chat_id
                )
                await queue.put(
                    _sse_format(
                        ErrorEvent(code="internal_error", message="Turn failed")
                    )
                )
            finally:
                latency_ms = round((perf_counter() - started_at) * 1000)
                add_sentry_breadcrumb(
                    category="companion",
                    message="Companion turn completed",
                    data={
                        "chat_id": str(chat_id),
                        **message_meta,
                        "latency_ms": latency_ms,
                        "event_count": event_count,
                        "failed": failed,
                    },
                )
                if not failed and latency_ms >= COMPANION_TURN_SLOW_THRESHOLD_MS:
                    capture_sentry_anomaly(
                        "companion.turn.slow",
                        "Companion turn latency exceeded threshold",
                        category="companion",
                        extras={
                            "chat_id": str(chat_id),
                            **message_meta,
                            "latency_ms": latency_ms,
                            "slow_threshold_ms": COMPANION_TURN_SLOW_THRESHOLD_MS,
                            "event_count": event_count,
                        },
                    )
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(
                        queue.get(), timeout=SSE_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield _SSE_HEARTBEAT
                    continue
                if frame is None:
                    break
                yield frame
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def sa_coalesce_last_message_or_created():
    """Use COALESCE(last_message_at, created_at) so brand-new chats sort by
    their creation time and only move once they have a real message."""
    from sqlalchemy import func

    return func.coalesce(Conversation.last_message_at, Conversation.created_at)
