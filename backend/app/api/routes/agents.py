"""Autonomous Wai agents: definitions, runs, timeline, and cancellation."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import Database, SessionUser
from app.config import get_settings
from app.core import agent_guard
from app.core.agent_capabilities import capabilities_response, validate_agent_config
from app.core.agent_dispatch import AgentDispatchError, enqueue_agent_run
from app.core.agent_runtime import (
    TERMINAL_STATUSES,
    cancel_run,
    execute_agent_step,
    pop_agent_runs_to_dispatch_after_commit,
    run_job,
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
from app.core.wai_agent import planner_for_agent
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.companion_pending_action import CompanionPendingAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

RUN_LEASE_TTL_SECONDS = 3600
RUN_EVENTS_POLL_SECONDS = 1.0
RUN_EVENTS_MAX_SECONDS = 60.0


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="custom", min_length=1, max_length=80)
    trigger_type: Literal["manual", "cron", "event", "signal", "chat"] = "manual"
    config: dict[str, Any] = Field(default_factory=dict)
    autonomy: Literal["propose"] = "propose"
    enabled: bool = True
    next_run_at: datetime | None = None


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, min_length=1, max_length=80)
    trigger_type: Literal["manual", "cron", "event", "signal", "chat"] | None = None
    config: dict[str, Any] | None = None
    autonomy: Literal["propose"] | None = None
    enabled: bool | None = None
    next_run_at: datetime | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    kind: str
    trigger_type: str
    config: dict[str, Any]
    autonomy: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]


class AgentCapabilityResponse(BaseModel):
    id: str
    label: str
    category: str
    description: str
    availability: str
    runtime_tool: str | None
    surfaces: list[str]
    requires_approval: bool
    cloud_supported: bool
    self_host_supported: bool
    local_gateway_required: bool
    risk_level: str
    permission_scopes: list[str]
    safety_notes: str


class AgentToolContractResponse(BaseModel):
    name: str
    capability_id: str
    kind: str
    description: str
    side_effect: str
    requires_approval: bool
    args_schema: dict[str, Any]
    result_schema: dict[str, Any]
    permission_scopes: list[str]


class AgentRuntimeModeResponse(BaseModel):
    id: str
    label: str
    description: str
    available: bool


class AgentCapabilitiesResponse(BaseModel):
    schema_version: str
    deployment_mode: str
    max_steps: int
    runtime_modes: list[AgentRuntimeModeResponse]
    capabilities: list[AgentCapabilityResponse]
    tool_contracts: list[AgentToolContractResponse]


class StartRunRequest(BaseModel):
    trigger_kind: Literal[
        "manual", "cron", "event", "signal", "chat", "telegram", "agent"
    ] = "manual"
    trigger_payload: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=120)
    run_inline: bool = False


class CancelRunRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AgentRunResponse(BaseModel):
    id: str
    agent_id: str
    conversation_id: str | None
    parent_run_id: str | None
    parent_step_idx: int | None
    trigger_key: str
    trigger_kind: str
    trigger_payload: dict[str, Any] | None
    status: str
    plan: dict[str, Any] | None
    done_spec: dict[str, Any] | None
    result: dict[str, Any] | None
    content_hash: str | None
    error: str | None
    next_step_idx: int
    heartbeat_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunResponse]


class AgentStepResponse(BaseModel):
    id: str
    run_id: str
    idx: int
    kind: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime


class AgentStepListResponse(BaseModel):
    steps: list[AgentStepResponse]


class AgentActionResponse(BaseModel):
    id: str
    agent_id: str | None
    run_id: str | None
    step_idx: int | None
    kind: str
    tool: str
    status: str
    preview: str
    recipient: str | None
    expires_at: datetime
    resolved_at: datetime | None
    receipt: dict[str, Any] | None


class AgentActionListResponse(BaseModel):
    actions: list[AgentActionResponse]


class ResolveAgentActionRequest(BaseModel):
    decision: Literal["once", "always", "reject"]
    edited_args: dict[str, Any] | None = None


class ResolveAgentActionResponse(BaseModel):
    action_id: str
    status: str
    run_status: str
    recipient: str | None = None


class DesktopResultRequest(BaseModel):
    device_id: UUID
    status: Literal["executed", "failed", "refused"]
    payload: dict[str, Any] | None = None


class DesktopResultResponse(BaseModel):
    action_id: str
    status: str
    run_status: str


def _agent_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        kind=agent.kind,
        trigger_type=agent.trigger_type,
        config=agent.config or {},
        autonomy=agent.autonomy,
        enabled=agent.enabled,
        next_run_at=agent.next_run_at,
        last_run_at=agent.last_run_at,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=str(run.id),
        agent_id=str(run.agent_id),
        conversation_id=str(run.conversation_id) if run.conversation_id else None,
        parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
        parent_step_idx=run.parent_step_idx,
        trigger_key=run.trigger_key,
        trigger_kind=run.trigger_kind,
        trigger_payload=run.trigger_payload,
        status=run.status,
        plan=run.plan,
        done_spec=run.done_spec,
        result=run.result,
        content_hash=run.content_hash,
        error=run.error,
        next_step_idx=run.next_step_idx,
        heartbeat_at=run.heartbeat_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        cancel_requested_at=run.cancel_requested_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _step_response(step: AgentStep) -> AgentStepResponse:
    return AgentStepResponse(
        id=str(step.id),
        run_id=str(step.run_id),
        idx=step.idx,
        kind=step.kind,
        payload=step.payload,
        idempotency_key=step.idempotency_key,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


def _action_response(
    row: CompanionPendingAction, *, agent_id: UUID | None = None
) -> AgentActionResponse:
    manifest = row.action_manifest or {}
    return AgentActionResponse(
        id=str(row.id),
        agent_id=str(agent_id) if agent_id else None,
        run_id=str(row.agent_run_id) if row.agent_run_id else None,
        step_idx=row.agent_step_idx,
        kind=row.kind,
        tool=row.tool_name,
        status=row.status,
        preview=str(manifest.get("preview") or ""),
        recipient=row.recipient_display,
        expires_at=row.expires_at,
        resolved_at=row.resolved_at,
        receipt=row.receipt,
    )


def _validate_config_or_422(config: dict[str, Any]) -> None:
    try:
        validate_agent_config(config)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _validate_schedule_or_422(trigger_type: str, config: dict[str, Any]) -> None:
    if trigger_type != "cron":
        return
    interval = config.get("interval_minutes")
    if isinstance(interval, bool):
        minutes = None
    else:
        try:
            minutes = int(interval)
        except (TypeError, ValueError):
            minutes = None
    if minutes is None or minutes < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cron agents require config.interval_minutes >= 1",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_agent(db: Database, user_id: UUID, agent_id: UUID) -> Agent:
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


async def _load_run(
    db: Database, user_id: UUID, agent_id: UUID, run_id: UUID
) -> AgentRun:
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.agent_id == agent_id,
                AgentRun.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _event_session_maker(db: Database) -> async_sessionmaker[AsyncSession]:
    if db.bind is None:
        raise RuntimeError("Agent event stream cannot resolve database bind")
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


async def _dispatch_queued_child_runs_or_fail(db: Database) -> None:
    run_ids = pop_agent_runs_to_dispatch_after_commit(db)
    if not run_ids:
        return
    await db.flush()
    await db.commit()
    for run_id in run_ids:
        try:
            enqueue_agent_run(run_id)
        except AgentDispatchError as exc:
            child = (
                await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            ).scalar_one_or_none()
            if child is not None:
                child.status = "failed"
                child.error = exc.message
                child.finished_at = _now()
                await db.flush()
                await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=exc.message,
            ) from exc


async def _run_inline(db: Database, run: AgentRun) -> AgentRun:
    if await agent_guard.agents_halted():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agents are halted",
        )
    try:
        await agent_guard.check_run_budget(str(run.user_id))
    except agent_guard.AgentGuardError as exc:
        headers = (
            {"Retry-After": str(exc.retry_after)}
            if exc.retry_after is not None
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.message,
            headers=headers,
        ) from exc
    lease = await agent_guard.acquire_run_slot(
        str(run.user_id), lease_ttl_seconds=RUN_LEASE_TTL_SECONDS
    )
    if lease is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent agent runs",
        )
    try:
        await agent_guard.record_run(str(run.user_id))
        agent = (
            await db.execute(select(Agent).where(Agent.id == run.agent_id))
        ).scalar_one_or_none()
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            )
        return await run_job(
            db,
            run.id,
            planner=planner_for_agent(agent),
            executor=execute_agent_step,
        )
    finally:
        await agent_guard.release_run_slot(str(run.user_id), lease)


_APPROVAL_HTTP_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "already_resolved": status.HTTP_409_CONFLICT,
    "expired": status.HTTP_410_GONE,
    "payload_tampered": status.HTTP_409_CONFLICT,
    "bad_decision": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


async def _resume_after_action(db: Database, run: AgentRun) -> AgentRun:
    agent = (
        await db.execute(select(Agent).where(Agent.id == run.agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    resumed = await run_job(
        db,
        run.id,
        planner=planner_for_agent(agent),
        executor=execute_agent_step,
    )
    await _dispatch_queued_child_runs_or_fail(db)
    return resumed


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: AgentCreateRequest,
    user: SessionUser,
    db: Database,
) -> AgentResponse:
    _validate_config_or_422(request.config)
    _validate_schedule_or_422(request.trigger_type, request.config)
    agent = Agent(
        user_id=user.id,
        name=request.name,
        kind=request.kind,
        trigger_type=request.trigger_type,
        config=request.config,
        autonomy=request.autonomy,
        enabled=request.enabled,
        next_run_at=request.next_run_at,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return _agent_response(agent)


@router.get("", response_model=AgentListResponse)
async def list_agents(
    user: SessionUser,
    db: Database,
    limit: int = Query(100, ge=1, le=500),
) -> AgentListResponse:
    result = await db.execute(
        select(Agent)
        .where(Agent.user_id == user.id)
        .order_by(Agent.created_at.desc())
        .limit(limit)
    )
    agents = list(result.scalars().all())
    return AgentListResponse(agents=[_agent_response(a) for a in agents])


@router.get("/capabilities", response_model=AgentCapabilitiesResponse)
async def get_agent_capabilities(user: SessionUser) -> AgentCapabilitiesResponse:
    return AgentCapabilitiesResponse(
        **capabilities_response(deployment_mode=get_settings().deployment_mode)
    )


@router.get("/runs", response_model=AgentRunListResponse)
async def list_user_agent_runs(
    user: SessionUser,
    db: Database,
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    limit: int = Query(50, ge=1, le=200),
) -> AgentRunListResponse:
    stmt = select(AgentRun).where(AgentRun.user_id == user.id)
    if status_filter:
        stmt = stmt.where(AgentRun.status == status_filter)
    result = await db.execute(stmt.order_by(AgentRun.created_at.desc()).limit(limit))
    return AgentRunListResponse(runs=[_run_response(run) for run in result.scalars().all()])


@router.get("/actions", response_model=AgentActionListResponse)
async def list_user_agent_actions(
    user: SessionUser,
    db: Database,
    status_filter: str | None = Query(default="pending", alias="status", max_length=40),
    limit: int = Query(50, ge=1, le=200),
) -> AgentActionListResponse:
    stmt = (
        select(CompanionPendingAction, AgentRun.agent_id)
        .join(AgentRun, AgentRun.id == CompanionPendingAction.agent_run_id)
        .where(
            CompanionPendingAction.user_id == user.id,
            AgentRun.user_id == user.id,
            CompanionPendingAction.agent_run_id.is_not(None),
        )
    )
    if status_filter:
        stmt = stmt.where(CompanionPendingAction.status == status_filter)
    result = await db.execute(
        stmt.order_by(CompanionPendingAction.created_at).limit(limit)
    )
    return AgentActionListResponse(
        actions=[
            _action_response(row, agent_id=agent_id)
            for row, agent_id in result.all()
        ]
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    user: SessionUser,
    db: Database,
) -> AgentResponse:
    return _agent_response(await _load_agent(db, user.id, agent_id))


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    request: AgentUpdateRequest,
    user: SessionUser,
    db: Database,
) -> AgentResponse:
    agent = await _load_agent(db, user.id, agent_id)
    data = request.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        _validate_config_or_422(data["config"])
    next_trigger_type = data.get("trigger_type", agent.trigger_type)
    next_config = data.get("config", agent.config or {})
    _validate_schedule_or_422(next_trigger_type, next_config)
    for field, value in data.items():
        setattr(agent, field, value)
    await db.flush()
    await db.refresh(agent)
    return _agent_response(agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_agent(
    agent_id: UUID,
    user: SessionUser,
    db: Database,
) -> Response:
    agent = await _load_agent(db, user.id, agent_id)
    await db.delete(agent)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{agent_id}/runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_agent_run(
    agent_id: UUID,
    request: StartRunRequest,
    user: SessionUser,
    db: Database,
) -> AgentRunResponse:
    agent = await _load_agent(db, user.id, agent_id)
    if not agent.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent disabled")

    idempotency_key = request.idempotency_key or uuid4().hex
    trigger_key = f"{request.trigger_kind}:{agent.id}:{idempotency_key}"
    existing = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.user_id == user.id,
                AgentRun.trigger_key == trigger_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _run_response(existing)

    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=trigger_key,
        trigger_kind=request.trigger_kind,
        trigger_payload=request.trigger_payload,
        content_hash=request.content_hash,
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent run already exists for this trigger",
        ) from exc

    if request.run_inline:
        run = await _run_inline(db, run)
        await _dispatch_queued_child_runs_or_fail(db)
    else:
        await _dispatch_run_or_fail(db, run)
    await db.refresh(run)
    return _run_response(run)


@router.get("/{agent_id}/runs", response_model=AgentRunListResponse)
async def list_agent_runs(
    agent_id: UUID,
    user: SessionUser,
    db: Database,
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    limit: int = Query(50, ge=1, le=200),
) -> AgentRunListResponse:
    await _load_agent(db, user.id, agent_id)
    stmt = select(AgentRun).where(
        AgentRun.agent_id == agent_id,
        AgentRun.user_id == user.id,
    )
    if status_filter:
        stmt = stmt.where(AgentRun.status == status_filter)
    result = await db.execute(stmt.order_by(AgentRun.created_at.desc()).limit(limit))
    return AgentRunListResponse(runs=[_run_response(run) for run in result.scalars().all()])


@router.get("/{agent_id}/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    agent_id: UUID,
    run_id: UUID,
    user: SessionUser,
    db: Database,
) -> AgentRunResponse:
    return _run_response(await _load_run(db, user.id, agent_id, run_id))


@router.get(
    "/{agent_id}/runs/{run_id}/steps",
    response_model=AgentStepListResponse,
)
async def list_agent_run_steps(
    agent_id: UUID,
    run_id: UUID,
    user: SessionUser,
    db: Database,
) -> AgentStepListResponse:
    await _load_run(db, user.id, agent_id, run_id)
    result = await db.execute(
        select(AgentStep)
        .where(AgentStep.run_id == run_id)
        .order_by(AgentStep.idx)
    )
    return AgentStepListResponse(
        steps=[_step_response(step) for step in result.scalars().all()]
    )


@router.get("/{agent_id}/runs/{run_id}/events")
async def stream_agent_run_events(
    agent_id: UUID,
    run_id: UUID,
    user: SessionUser,
    db: Database,
) -> StreamingResponse:
    await _load_run(db, user.id, agent_id, run_id)
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
                    yield (
                        f"event: step\ndata: {json.dumps(payload)}\n\n"
                    ).encode("utf-8")
                run = await _load_run(event_db, user.id, agent_id, run_id)
            if run.status in TERMINAL_STATUSES or run.status == "awaiting_approval":
                payload = _run_response(run).model_dump(mode="json")
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


@router.post(
    "/{agent_id}/runs/{run_id}/cancel",
    response_model=AgentRunResponse,
)
async def cancel_agent_run(
    agent_id: UUID,
    run_id: UUID,
    request: CancelRunRequest,
    user: SessionUser,
    db: Database,
) -> AgentRunResponse:
    run = await _load_run(db, user.id, agent_id, run_id)
    await cancel_run(db, run, reason=request.reason)
    await db.refresh(run)
    return _run_response(run)


@router.get(
    "/{agent_id}/runs/{run_id}/actions",
    response_model=AgentActionListResponse,
)
async def list_agent_run_actions(
    agent_id: UUID,
    run_id: UUID,
    user: SessionUser,
    db: Database,
) -> AgentActionListResponse:
    await _load_run(db, user.id, agent_id, run_id)
    result = await db.execute(
        select(CompanionPendingAction)
        .where(
            CompanionPendingAction.user_id == user.id,
            CompanionPendingAction.agent_run_id == run_id,
        )
        .order_by(CompanionPendingAction.created_at)
    )
    return AgentActionListResponse(
        actions=[
            _action_response(row, agent_id=agent_id)
            for row in result.scalars().all()
        ]
    )


@router.post(
    "/{agent_id}/runs/{run_id}/actions/{action_id}/resolve",
    response_model=ResolveAgentActionResponse,
)
async def resolve_agent_action(
    agent_id: UUID,
    run_id: UUID,
    action_id: UUID,
    request: ResolveAgentActionRequest,
    user: SessionUser,
    db: Database,
) -> ResolveAgentActionResponse:
    run = await _load_run(db, user.id, agent_id, run_id)
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent run is already terminal",
        )
    existing = await get_pending(db, action_id=action_id, user_id=user.id, lock=False)
    if existing is None or existing.agent_run_id != run.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending action not found for this run",
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
        if exc.code == "expired":
            await db.commit()
        raise HTTPException(
            status_code=_APPROVAL_HTTP_STATUS.get(
                exc.code, status.HTTP_400_BAD_REQUEST
            ),
            detail=exc.message,
        ) from exc

    if request.decision == "reject":
        run = await _resume_after_action(db, run)
        return ResolveAgentActionResponse(
            action_id=str(action_id),
            status="rejected",
            run_status=run.status,
            recipient=row.recipient_display,
        )

    try:
        verify_committable(row)
        if row.kind == "desktop_action":
            run = await _resume_after_action(db, run)
            return ResolveAgentActionResponse(
                action_id=str(action_id),
                status="dispatched",
                run_status=run.status,
                recipient=row.recipient_display,
            )
        args = (row.action_manifest or {}).get("args") or {}
        receipt = await execute_action(
            db, user_id=user.id, tool_name=row.tool_name, args=args
        )
        await mark_executed(db, row=row, receipt=receipt)
        run = await _resume_after_action(db, run)
    except (ApprovalError, ActuationError) as exc:
        await mark_failed(db, row=row, detail=exc.message)
        run = await _resume_after_action(db, run)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
            headers={"X-Agent-Run-Status": run.status},
        ) from exc

    return ResolveAgentActionResponse(
        action_id=str(action_id),
        status="executed",
        run_status=run.status,
        recipient=row.recipient_display,
    )


@router.post(
    "/{agent_id}/runs/{run_id}/actions/{action_id}/desktop_result",
    response_model=DesktopResultResponse,
)
async def agent_desktop_action_result(
    agent_id: UUID,
    run_id: UUID,
    action_id: UUID,
    request: DesktopResultRequest,
    user: SessionUser,
    db: Database,
) -> DesktopResultResponse:
    run = await _load_run(db, user.id, agent_id, run_id)
    row = await get_pending(db, action_id=action_id, user_id=user.id, lock=True)
    if row is None or row.kind != "desktop_action" or row.agent_run_id != run.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Desktop action not found",
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
            return DesktopResultResponse(
                action_id=str(action_id),
                status=row.status,
                run_status=run.status,
            )
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
        run = await _resume_after_action(db, run)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
            headers={"X-Agent-Run-Status": run.status},
        ) from exc
    if request.status == "executed":
        await mark_executed(
            db, row=row, receipt=request.payload or {"status": "executed"}
        )
    else:
        await mark_failed(db, row=row, detail=request.status)
    run = await _resume_after_action(db, run)
    await db.refresh(row)
    return DesktopResultResponse(
        action_id=str(action_id),
        status=row.status,
        run_status=run.status,
    )
