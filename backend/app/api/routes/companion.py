"""Wai Companion REST routes — CRUD plus SSE message streaming."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from app.api.deps import CurrentUser, Database
from app.core.brain_spaces import (
    BrainSpaceNotFoundError,
    BrainSpacePermissionError,
    BrainSpaceValidationError,
    load_space_access,
)
from app.core.companion import (
    ActionProposedEvent,
    CompanionError,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    TurnContext,
    TurnStartEvent,
    run_turn,
)
from app.core.companion_actions import (
    ApprovalError,
    get_pending,
    mark_executed,
    mark_failed,
    resolve_action,
    verify_committable,
)
from app.core.companion_actuators import ActuationError, execute_action
from app.core.device_presence import get_owned_device
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_anomaly,
    safe_query_metadata,
)
from app.core.wai_agent import run_wai_run_inline, start_wai_task
from app.models.companion import ChatMessage, Conversation, MessageCitation
from app.models.companion_pending_action import CompanionPendingAction
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

    Every accepted field must be enforced server-side. `recording_ids` narrows
    recording retrieval; `brain_space_id` injects approved Brain knowledge.
    """

    recording_ids: list[str] | None = None
    brain_space_id: str | None = None


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


async def _validated_scope_to_jsonb(
    db: Database,
    user_id: uuid.UUID,
    scope: ConversationScope | None,
) -> dict[str, Any] | None:
    body = _scope_to_jsonb(scope)
    if not body or not body.get("brain_space_id"):
        return body
    try:
        brain_space_id = uuid.UUID(str(body["brain_space_id"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Malformed brain_space_id: {exc}",
        ) from exc
    try:
        await load_space_access(db, user_id, brain_space_id)
    except BrainSpaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brain scope not found",
        ) from exc
    except BrainSpacePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brain scope is not available to this user",
        ) from exc
    except BrainSpaceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return body


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
        scope=await _validated_scope_to_jsonb(db, user.id, request.scope),
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
        chat.scope = await _validated_scope_to_jsonb(db, user.id, request.scope)
    if request.pinned is not None:
        chat.pinned_at = datetime.now(timezone.utc) if request.pinned else None
    if request.archived is not None:
        chat.archived_at = datetime.now(timezone.utc) if request.archived else None

    await db.flush()
    await db.refresh(chat)
    return _to_summary(chat)


@router.delete(
    "/chats/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_chat(
    chat_id: uuid.UUID,
    user: CurrentUser,
    db: Database,
) -> Response:
    chat = await _load_user_chat(db, user.id, chat_id)
    chat.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    # Client-advertised capabilities so the server can withhold SSE event types
    # an older client cannot parse (the Swift CompanionStream parser THROWS on
    # unknown event types). New action/desktop/narration events are gated behind
    # "actions_v1"; clients that omit it fail closed — a withheld approval simply
    # never arrives and times out == deny.
    client_capabilities: list[str] = Field(default_factory=list)


def _sse_format(event_obj: Any) -> bytes:
    """Serialize a CompanionEvent dataclass as a single SSE frame."""
    data = asdict(event_obj)
    event_type = data.pop("type")
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


# Event types added after the v1 clients shipped. Emitted ONLY to clients that
# advertise the matching capability; older clients never receive an event they
# cannot decode (the Swift CompanionStream parser THROWS on unknown types, so
# this fails closed). actions_v1 = approval/desktop/narration; agent_chat_v2 =
# the streaming agent surface (thinking + plan; tool_call/tool_result ride the
# v1 union and stay ungated since both shipped clients already decode them).
_CLIENT_CAP_ACTIONS = "actions_v1"
_CLIENT_CAP_CHAT_V2 = "agent_chat_v2"
_EVENT_REQUIRED_CAPABILITY: dict[str, str] = {
    "action_proposed": _CLIENT_CAP_ACTIONS,
    "action_result": _CLIENT_CAP_ACTIONS,
    "narration": _CLIENT_CAP_ACTIONS,
    "desktop_action": _CLIENT_CAP_ACTIONS,
    "thinking": _CLIENT_CAP_CHAT_V2,
    "plan": _CLIENT_CAP_CHAT_V2,
    "artifact": _CLIENT_CAP_CHAT_V2,
}


def _client_can_receive(event_obj: Any, capabilities: list[str]) -> bool:
    required = _EVENT_REQUIRED_CAPABILITY.get(getattr(event_obj, "type", ""))
    return required is None or required in capabilities


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


def _active_context_from_request(
    request: PostMessageRequest,
    *,
    viewing_recording_title: str | None,
) -> dict[str, Any] | None:
    if request.viewing_recording_id is None:
        return None
    context: dict[str, Any] = {
        "ref_type": "recording",
        "ref_id": str(request.viewing_recording_id),
        "source": "companion",
    }
    if viewing_recording_title:
        context["title"] = viewing_recording_title
    return context


async def _run_wai_companion_turn(
    db: Database,
    *,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    user_text: str,
    context: dict[str, Any] | None,
    client_capabilities: list[str] | None = None,
    turn_context: TurnContext | None = None,
) -> AsyncIterator[Any]:
    # Clients advertising agent_chat_v2 get the streaming LLM agent (run_turn):
    # live token deltas, visible tool actions (brain reads + web search), gated
    # write approvals, thinking + plan events. Older clients stay on the durable
    # agent runtime, which runs to completion and emits one final message.
    if client_capabilities and _CLIENT_CAP_CHAT_V2 in client_capabilities:
        async for evt in run_turn(
            db,
            user_id,
            chat_id,
            user_text,
            turn_context=turn_context,
            enable_actions=True,
            stream_reasoning=True,
        ):
            yield evt
        return

    _conversation, run, _created = await start_wai_task(
        db,
        user_id=user_id,
        objective=user_text,
        conversation_id=chat_id,
        context=context,
        trigger_kind="chat",
        idempotency_key=uuid.uuid4().hex,
    )
    payload = run.trigger_payload or {}
    yield TurnStartEvent(
        message_id=str(payload.get("user_message_id") or ""),
        conversation_id=str(chat_id),
    )

    run = await run_wai_run_inline(db, run)
    if run.status == "failed":
        raise CompanionError("wai_agent_failed", run.error or "Wai task failed")

    if run.status == "awaiting_approval":
        actions = (
            await db.execute(
                select(CompanionPendingAction)
                .where(
                    CompanionPendingAction.user_id == user_id,
                    CompanionPendingAction.agent_run_id == run.id,
                    CompanionPendingAction.status == "pending",
                )
                .order_by(CompanionPendingAction.created_at, CompanionPendingAction.id)
            )
        ).scalars().all()
        for action in actions:
            manifest = action.action_manifest or {}
            yield ActionProposedEvent(
                action_id=str(action.id),
                kind=action.kind,
                tool=action.tool_name,
                preview=str(manifest.get("preview") or ""),
                expires_at=action.expires_at.isoformat(),
                recipient=action.recipient_display,
            )
        return

    result = run.result or {}
    output_text = str(result.get("output_text") or "").strip()
    if not output_text:
        raise CompanionError("empty_agent_output", "Wai task completed without output.")

    assistant_msg = ChatMessage(
        conversation_id=chat_id,
        role="assistant",
        content=[{"type": "text", "text": output_text}],
        model="wai-agent",
        latency_ms=0,
    )
    db.add(assistant_msg)
    conversation = await db.get(Conversation, chat_id)
    if conversation is not None:
        conversation.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(assistant_msg)

    yield TokenEvent(text=output_text)
    yield DoneEvent(
        message_id=str(assistant_msg.id),
        model="wai-agent",
        latency_ms=0,
    )


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

    viewing_recording_title, _viewing_folder_name = await _resolve_viewing_titles(
        db,
        user.id,
        request.viewing_recording_id,
        request.viewing_folder_id,
    )
    active_context = _active_context_from_request(
        request,
        viewing_recording_title=viewing_recording_title,
    )
    turn_context = TurnContext(
        client_local_date=request.client_local_date,
        client_timezone=request.client_timezone,
        viewing_recording_title=viewing_recording_title,
        viewing_folder_name=_viewing_folder_name,
    )

    async def event_stream():
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        async def producer() -> None:
            started_at = perf_counter()
            event_count = 0
            failed = False
            try:
                async for evt in _run_wai_companion_turn(
                    db,
                    user_id=user.id,
                    chat_id=chat_id,
                    user_text=request.content,
                    context=active_context,
                    client_capabilities=request.client_capabilities,
                    turn_context=turn_context,
                ):
                    event_count += 1
                    if _client_can_receive(evt, request.client_capabilities):
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


# HTTP status for each gate failure (errors are surfaced; no silent fallback).
_APPROVAL_HTTP_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "already_resolved": status.HTTP_409_CONFLICT,
    "expired": status.HTTP_410_GONE,
    "payload_tampered": status.HTTP_409_CONFLICT,
    "bad_decision": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


class ResolveActionRequest(BaseModel):
    decision: Literal["once", "always", "reject"]
    edited_args: dict[str, Any] | None = None


class ResolveActionResponse(BaseModel):
    action_id: str
    status: str  # "executed" | "rejected"
    recipient: str | None = None  # display name only, never a raw id


@router.post(
    "/chats/{chat_id}/actions/{action_id}/resolve",
    response_model=ResolveActionResponse,
)
async def resolve_chat_action(
    chat_id: uuid.UUID,
    action_id: uuid.UUID,
    request: ResolveActionRequest,
    user: CurrentUser,
    db: Database,
) -> ResolveActionResponse:
    """Approve (once/always) or reject a pending mutating action.

    On approval the payload HMAC is re-verified and the side effect runs exactly
    once (idempotent receipt). ``timeout == deny`` is enforced by resolve_action;
    every failure is surfaced as an HTTP error (no silent fallback). The response
    carries only a recipient *display name*, never a raw id/body.
    """
    await _load_user_chat(db, user.id, chat_id)  # ownership (404 otherwise)
    existing = await get_pending(db, action_id=action_id, user_id=user.id, lock=False)
    if existing is None or existing.conversation_id != chat_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending action not found for this chat",
        )

    try:
        row = await resolve_action(
            db,
            action_id=action_id,
            user_id=user.id,
            decision=request.decision,
            edited_args=request.edited_args,
        )
    except ApprovalError as exc:
        await db.commit()  # persist any expired-on-read transition
        raise HTTPException(
            status_code=_APPROVAL_HTTP_STATUS.get(
                exc.code, status.HTTP_400_BAD_REQUEST
            ),
            detail=exc.message,
        ) from exc

    if request.decision == "reject":
        await db.commit()
        return ResolveActionResponse(
            action_id=str(action_id),
            status="rejected",
            recipient=row.recipient_display,
        )

    # Approved → re-verify the locked payload, then execute exactly once.
    try:
        verify_committable(row)
        if row.kind == "desktop_action":
            # Dispatched to the Mac edge — NOT run server-side. It stays
            # "approved" in the device drain queue and is marked executed only
            # when the Mac reports back via /desktop_result.
            await db.commit()
            return ResolveActionResponse(
                action_id=str(action_id),
                status="dispatched",
                recipient=row.recipient_display,
            )
        args = (row.action_manifest or {}).get("args") or {}
        receipt = await execute_action(
            db, user_id=user.id, tool_name=row.tool_name, args=args
        )
        await mark_executed(db, row=row, receipt=receipt)
        await db.commit()
    except (ApprovalError, ActuationError) as exc:
        await mark_failed(db, row=row, detail=exc.message)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
        ) from exc

    return ResolveActionResponse(
        action_id=str(action_id),
        status="executed",
        recipient=row.recipient_display,
    )


class DesktopResultRequest(BaseModel):
    device_id: uuid.UUID
    status: Literal["executed", "failed", "refused"]
    payload: dict[str, Any] | None = None


class DesktopResultResponse(BaseModel):
    action_id: str
    status: str


@router.post(
    "/chats/{chat_id}/actions/{action_id}/desktop_result",
    response_model=DesktopResultResponse,
)
async def desktop_action_result(
    chat_id: uuid.UUID,
    action_id: uuid.UUID,
    request: DesktopResultRequest,
    user: CurrentUser,
    db: Database,
) -> DesktopResultResponse:
    """The Mac reports the outcome of a dispatched desktop action. Idempotent
    (mark_executed is a no-op once recorded). A result is only accepted for an
    already-approved action — a report can never mark an unapproved action done
    (no approval bypass)."""
    await _load_user_chat(db, user.id, chat_id)
    row = await get_pending(db, action_id=action_id, user_id=user.id, lock=True)
    if row is None or row.conversation_id != chat_id or row.kind != "desktop_action":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Desktop action not found"
        )
    device = await get_owned_device(db, user_id=user.id, device_id=request.device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    if row.device_target is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desktop action has no target device",
        )
    if row.device_target != str(request.device_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desktop action is not targeted at this device",
        )
    if row.status in ("executed", "failed"):
        duplicate_success = row.status == "executed" and request.status == "executed"
        duplicate_failure = row.status == "failed" and request.status in ("failed", "refused")
        if duplicate_success or duplicate_failure:
            return DesktopResultResponse(action_id=str(action_id), status=row.status)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desktop action result already recorded",
        )
    if row.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Desktop action is not dispatched",
        )
    try:
        verify_committable(row)
    except ApprovalError as exc:
        await mark_failed(db, row=row, detail=exc.message)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        ) from exc
    if request.status == "executed":
        await mark_executed(
            db, row=row, receipt=request.payload or {"status": "executed"}
        )
    else:
        await mark_failed(db, row=row, detail=request.status)
    await db.commit()
    return DesktopResultResponse(action_id=str(action_id), status=row.status)
