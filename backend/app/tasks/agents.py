"""Celery tasks for autonomous Wai agents."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core import agent_guard
from app.core.agent_runtime import (
    execute_agent_step,
    pop_agent_runs_to_dispatch_after_commit,
    run_job,
)
from app.core.agent_runtime import (
    static_config_planner as static_config_planner,
)
from app.core.companion_actions import expire_due_actions
from app.core.wai_agent import planner_for_agent
from app.db.session import get_db_context
from app.models.agent import Agent, AgentRun
from app.models.companion_pending_action import CompanionPendingAction
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

RUN_LEASE_TTL_SECONDS = 3600
STALE_AFTER_SECONDS = 900


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _mark_failed(run: AgentRun, message: str) -> None:
    run.status = "failed"
    run.error = message[:2000]
    run.finished_at = _now()


async def _dispatch_child_runs_after_commit(run_ids: list[UUID]) -> None:
    for run_id in run_ids:
        try:
            run.delay(str(run_id))
        except Exception as exc:  # noqa: BLE001
            async with get_db_context() as db:
                run_row = (
                    await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                ).scalar_one_or_none()
                if run_row is not None:
                    await _mark_failed(
                        run_row,
                        f"Could not enqueue delegated agent run: {type(exc).__name__}",
                    )
                    await db.flush()


async def _run_agent_async(run_id: str) -> str:
    child_run_ids: list[UUID] = []
    final_status = "failed"
    async with get_db_context() as db:
        run = (
            await db.execute(select(AgentRun).where(AgentRun.id == UUID(run_id)))
        ).scalar_one_or_none()
        if run is None:
            raise RuntimeError(f"agent run not found: {run_id}")

        if await agent_guard.agents_halted():
            await _mark_failed(run, "Agents are halted")
            return "failed"

        try:
            await agent_guard.check_run_budget(str(run.user_id))
        except agent_guard.AgentGuardError as exc:
            await _mark_failed(run, exc.message)
            return "failed"

        lease = await agent_guard.acquire_run_slot(
            str(run.user_id), lease_ttl_seconds=RUN_LEASE_TTL_SECONDS
        )
        if lease is None:
            run.status = "pending"
            run.error = "Too many concurrent agent runs"
            return "deferred"

        try:
            await agent_guard.record_run(str(run.user_id))
            agent = (
                await db.execute(select(Agent).where(Agent.id == run.agent_id))
            ).scalar_one_or_none()
            if agent is None:
                await _mark_failed(run, "Agent not found")
                return "failed"
            run = await run_job(
                db,
                run.id,
                planner=planner_for_agent(agent),
                executor=execute_agent_step,
            )
            final_status = run.status
            child_run_ids = pop_agent_runs_to_dispatch_after_commit(db)
        finally:
            await agent_guard.release_run_slot(str(run.user_id), lease)
    await _dispatch_child_runs_after_commit(child_run_ids)
    return final_status


@celery_app.task(name="app.tasks.agents.run")
def run(run_id: str) -> str:
    return asyncio.run(_run_agent_async(run_id))


def _next_run_at(agent: Agent, now: datetime) -> datetime | None:
    interval = (agent.config or {}).get("interval_minutes")
    if interval is None:
        return None
    try:
        minutes = int(interval)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return now + timedelta(minutes=minutes)


async def _dispatch_due_agents_async(limit: int = 50) -> int:
    now = _now()
    dispatched = 0
    run_ids_to_dispatch: list[tuple[str, UUID, datetime | None, datetime]] = []
    async with get_db_context() as db:
        result = await db.execute(
            select(Agent)
            .where(
                Agent.enabled.is_(True),
                Agent.trigger_type == "cron",
                Agent.next_run_at.is_not(None),
                Agent.next_run_at <= now,
            )
            .order_by(Agent.next_run_at)
            .limit(limit)
        )
        for agent in result.scalars().all():
            trigger_key = f"cron:{agent.id}:{now.strftime('%Y%m%dT%H%M')}"
            existing = (
                await db.execute(
                    select(AgentRun).where(AgentRun.trigger_key == trigger_key)
                )
            ).scalar_one_or_none()
            if existing is None:
                run_row = AgentRun(
                    agent_id=agent.id,
                    user_id=agent.user_id,
                    trigger_key=trigger_key,
                    trigger_kind="cron",
                    trigger_payload={"scheduled_for": now.isoformat()},
                )
                db.add(run_row)
                await db.flush()
                run_ids_to_dispatch.append(
                    (str(run_row.id), agent.id, _next_run_at(agent, now), now)
                )
        await db.commit()
    for run_id, agent_id, next_run_at, dispatched_at in run_ids_to_dispatch:
        try:
            run.delay(run_id)
        except Exception as exc:  # noqa: BLE001
            async with get_db_context() as db:
                run_row = (
                    await db.execute(select(AgentRun).where(AgentRun.id == UUID(run_id)))
                ).scalar_one_or_none()
                if run_row is not None:
                    await _mark_failed(
                        run_row,
                        f"Could not enqueue agent run: {type(exc).__name__}",
                    )
                    await db.flush()
                    await db.commit()
            continue
        async with get_db_context() as db:
            agent = (
                await db.execute(select(Agent).where(Agent.id == agent_id))
            ).scalar_one_or_none()
            if agent is not None:
                agent.next_run_at = next_run_at
                agent.last_run_at = dispatched_at
                await db.flush()
                await db.commit()
        dispatched += 1
    return dispatched


@celery_app.task(name="app.tasks.agents.dispatch_due_agents")
def dispatch_due_agents(limit: int = 50) -> int:
    return asyncio.run(_dispatch_due_agents_async(limit=limit))


async def _recover_stale_agent_runs_async(limit: int = 50) -> int:
    cutoff = _now() - timedelta(seconds=STALE_AFTER_SECONDS)
    recovered = 0
    async with get_db_context() as db:
        now = _now()
        stale_active_run = AgentRun.status.in_(["planning", "running"]) & (
            (
                AgentRun.heartbeat_at.is_not(None)
                & (AgentRun.heartbeat_at < cutoff)
            )
            | (
                AgentRun.heartbeat_at.is_(None)
                & (AgentRun.created_at < cutoff)
            )
        )
        stale_pending_run = (
            (AgentRun.status == "pending")
            & (AgentRun.created_at < cutoff)
            & (
                AgentRun.heartbeat_at.is_(None)
                | (AgentRun.heartbeat_at < cutoff)
            )
        )
        result = await db.execute(
            select(AgentRun)
            .where(stale_active_run | stale_pending_run)
            .order_by(AgentRun.created_at)
            .limit(limit)
        )
        for run_row in result.scalars().all():
            try:
                run.delay(str(run_row.id))
            except Exception as exc:  # noqa: BLE001
                await _mark_failed(
                    run_row,
                    f"Could not enqueue stale agent run: {type(exc).__name__}",
                )
                continue
            run_row.heartbeat_at = now
            recovered += 1
        await db.flush()
    return recovered


@celery_app.task(name="app.tasks.agents.recover_stale_agent_runs")
def recover_stale_agent_runs(limit: int = 50) -> int:
    return asyncio.run(_recover_stale_agent_runs_async(limit=limit))


async def _expire_due_actions_async() -> int:
    child_run_ids: list[UUID] = []
    async with get_db_context() as db:
        now = _now()
        result = await db.execute(
            select(CompanionPendingAction.agent_run_id)
            .where(
                CompanionPendingAction.agent_run_id.is_not(None),
                CompanionPendingAction.status.in_(["pending", "approved"]),
                CompanionPendingAction.expires_at <= now,
            )
            .distinct()
        )
        run_ids = [row[0] for row in result.all() if row[0] is not None]
        count = await expire_due_actions(db, now=now)
        for run_id in run_ids:
            run = (
                await db.execute(
                    select(AgentRun).where(
                        AgentRun.id == run_id,
                        AgentRun.status == "awaiting_approval",
                    )
                )
            ).scalar_one_or_none()
            if run is not None:
                agent = (
                    await db.execute(select(Agent).where(Agent.id == run.agent_id))
                ).scalar_one_or_none()
                if agent is None:
                    await _mark_failed(run, "Agent not found")
                    continue
                await run_job(
                    db,
                    run.id,
                    planner=planner_for_agent(agent),
                    executor=execute_agent_step,
                )
                child_run_ids.extend(pop_agent_runs_to_dispatch_after_commit(db))
    await _dispatch_child_runs_after_commit(child_run_ids)
    return count


@celery_app.task(name="app.tasks.agents.expire_due_actions")
def expire_due_action_rows() -> int:
    return asyncio.run(_expire_due_actions_async())
