"""Wai agent session API."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import CurrentUser, Database
from app.core.agent_dispatch import AgentDispatchError, enqueue_agent_run
from app.core.agent_runtime import TERMINAL_STATUSES
from app.core.wai_agent import ensure_wai_session, run_wai_run_inline, start_wai_task
from app.models.agent import AgentRun, AgentStep
from app.models.companion import Conversation

router = APIRouter(prefix="/wai", tags=["wai"])

RUN_EVENTS_POLL_SECONDS = 1.0
RUN_EVENTS_MAX_SECONDS = 60.0


class WaiSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    context: dict[str, Any] | None = None


class WaiTaskRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    context: dict[str, Any] | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)
    run_inline: bool = False


class WaiSessionResponse(BaseModel):
    id: str
    title: str | None
    scope: dict[str, Any] | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WaiRunResponse(BaseModel):
    id: str
    agent_id: str
    conversation_id: str | None
    trigger_key: str
    trigger_kind: str
    trigger_payload: dict[str, Any] | None
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class WaiStepResponse(BaseModel):
    id: str
    run_id: str
    idx: int
    kind: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime


class WaiSessionDetailResponse(WaiSessionResponse):
    latest_run: WaiRunResponse | None = None
    steps: list[WaiStepResponse] = Field(default_factory=list)


class WaiTaskResponse(BaseModel):
    session: WaiSessionResponse
    run: WaiRunResponse
    created: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_response(conversation: Conversation) -> WaiSessionResponse:
    return WaiSessionResponse(
        id=str(conversation.id),
        title=conversation.title,
        scope=conversation.scope,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _run_response(run: AgentRun) -> WaiRunResponse:
    return WaiRunResponse(
        id=str(run.id),
        agent_id=str(run.agent_id),
        conversation_id=str(run.conversation_id) if run.conversation_id else None,
        trigger_key=run.trigger_key,
        trigger_kind=run.trigger_kind,
        trigger_payload=run.trigger_payload,
        status=run.status,
        result=run.result,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _step_response(step: AgentStep) -> WaiStepResponse:
    return WaiStepResponse(
        id=str(step.id),
        run_id=str(step.run_id),
        idx=step.idx,
        kind=step.kind,
        payload=step.payload,
        idempotency_key=step.idempotency_key,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


async def _load_session(db: Database, user_id: UUID, session_id: UUID) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == session_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wai session not found")
    return conversation


async def _latest_run(db: Database, user_id: UUID, session_id: UUID) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.conversation_id == session_id,
            )
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _event_session_maker(db: Database) -> async_sessionmaker[AsyncSession]:
    if db.bind is None:
        raise RuntimeError("Wai event stream cannot resolve database bind")
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _dispatch_run_or_fail(db: Database, run: AgentRun) -> None:
    await db.flush()
    await db.commit()
    try:
        enqueue_agent_run(run.id)
    except AgentDispatchError as exc:
        run.status = "failed"
        run.error = exc.message
        run.finished_at = _now()
        await db.flush()
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc


@router.post("/sessions", response_model=WaiSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_wai_session(
    request: WaiSessionCreateRequest,
    user: CurrentUser,
    db: Database,
) -> WaiSessionResponse:
    conversation = await ensure_wai_session(
        db,
        user.id,
        title=request.title,
        context=request.context,
    )
    await db.refresh(conversation)
    return _session_response(conversation)


@router.get("/sessions/{session_id}", response_model=WaiSessionDetailResponse)
async def get_wai_session(
    session_id: UUID,
    user: CurrentUser,
    db: Database,
    steps_limit: int = Query(100, ge=1, le=500),
) -> WaiSessionDetailResponse:
    conversation = await _load_session(db, user.id, session_id)
    run = await _latest_run(db, user.id, conversation.id)
    steps: list[AgentStep] = []
    if run is not None:
        steps = list(
            (
                await db.execute(
                    select(AgentStep)
                    .where(AgentStep.run_id == run.id)
                    .order_by(AgentStep.idx)
                    .limit(steps_limit)
                )
            )
            .scalars()
            .all()
        )
    return WaiSessionDetailResponse(
        **_session_response(conversation).model_dump(),
        latest_run=_run_response(run) if run else None,
        steps=[_step_response(step) for step in steps],
    )


@router.post(
    "/sessions/{session_id}/tasks",
    response_model=WaiTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_wai_task(
    session_id: UUID,
    request: WaiTaskRequest,
    user: CurrentUser,
    db: Database,
) -> WaiTaskResponse:
    await _load_session(db, user.id, session_id)
    conversation, run, created = await start_wai_task(
        db,
        user_id=user.id,
        conversation_id=session_id,
        objective=request.objective,
        context=request.context,
        trigger_kind="chat",
        idempotency_key=request.idempotency_key,
    )
    if created:
        if request.run_inline:
            run = await run_wai_run_inline(db, run)
        else:
            await _dispatch_run_or_fail(db, run)
    await db.refresh(conversation)
    await db.refresh(run)
    return WaiTaskResponse(
        session=_session_response(conversation),
        run=_run_response(run),
        created=created,
    )


@router.post("/tasks", response_model=WaiTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_wai_task_in_new_session(
    request: WaiTaskRequest,
    user: CurrentUser,
    db: Database,
) -> WaiTaskResponse:
    conversation, run, created = await start_wai_task(
        db,
        user_id=user.id,
        objective=request.objective,
        context=request.context,
        trigger_kind="chat",
        idempotency_key=request.idempotency_key,
    )
    if created:
        if request.run_inline:
            run = await run_wai_run_inline(db, run)
        else:
            await _dispatch_run_or_fail(db, run)
    await db.refresh(conversation)
    await db.refresh(run)
    return WaiTaskResponse(
        session=_session_response(conversation),
        run=_run_response(run),
        created=created,
    )


@router.get("/sessions/{session_id}/events")
async def stream_wai_session_events(
    session_id: UUID,
    user: CurrentUser,
    db: Database,
) -> StreamingResponse:
    await _load_session(db, user.id, session_id)
    run = await _latest_run(db, user.id, session_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wai run not found")
    run_id = run.id
    await db.commit()
    event_sessions = _event_session_maker(db)

    async def event_stream():
        seen = -1
        elapsed = 0.0
        while elapsed <= RUN_EVENTS_MAX_SECONDS:
            async with event_sessions() as event_db:
                result = await event_db.execute(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id, AgentStep.idx > seen)
                    .order_by(AgentStep.idx)
                )
                steps = list(result.scalars().all())
                for step in steps:
                    seen = max(seen, step.idx)
                    payload = _step_response(step).model_dump(mode="json")
                    yield f"event: step\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
                latest = (
                    await event_db.execute(select(AgentRun).where(AgentRun.id == run_id))
                ).scalar_one()
            if latest.status in TERMINAL_STATUSES or latest.status == "awaiting_approval":
                payload = _run_response(latest).model_dump(mode="json")
                yield f"event: run\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
                break
            await asyncio.sleep(RUN_EVENTS_POLL_SECONDS)
            elapsed += RUN_EVENTS_POLL_SECONDS

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
