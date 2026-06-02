"""Stateless journalled harness for autonomous working-agents (P6) — the centerpiece.

``run_job(session, run_id, ...)`` REPLAYS the ``agent_steps`` journal so any Celery
worker can resume a run after an OOM/SIGKILL. The invariants it enforces:

* **Effectively-once** — a boundary already in the journal is never re-done; a
  resume replays it (``next_step_idx`` cursor + ``UNIQUE(run_id, idx)``).
* **Never forks** — ``trigger_key`` UNIQUE means one wake => one run, so a
  redelivered wake of a finished run is an idempotent no-op.
* **No fallbacks** — a missing run / agent SURFACES an error rather than guessing.
* **Skip-when-nothing-changed** — a wake whose input fingerprint matches the last
  success short-circuits with a journalled ``skip`` and does no model work.

Plan-then-execute: a Haiku-class ``planner`` produces a plan + ``done_spec`` exactly
once (journalled), execution appends ``tool_call`` / ``tool_result`` boundaries, and
a verifier checks the ``done_spec`` before ``final``. Built in slices — this slice
covers load + terminal-idempotency + skip + the journalled PLAN boundary with
replay-without-refork; execute / approve / verify / final land next.

Privacy: plan/step payloads MAY carry recipient/body — they stay in Postgres and
are NEVER logged raw (AGENTS.md).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentRun, AgentStep

# A run in one of these states is finished — run_job is a no-op (safe re-delivery).
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"done", "failed", "expired", "skipped"}
)


class AgentRuntimeError(Exception):
    """The harness could not proceed and must surface — never a silent fallback.

    Carries a machine ``code`` so callers (tasks/agents.py) can branch without
    string-matching.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentPlan:
    """A planner's output: the ordered plan + the ``done_spec`` the verifier checks."""

    plan: dict[str, Any]
    done_spec: dict[str, Any]


# Injectable planner. Real impl = a bounded Haiku-class LLM call; tests pass a fake.
Planner = Callable[[Agent, AgentRun], Awaitable[AgentPlan]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_run(session: AsyncSession, run_id: UUID) -> AgentRun:
    run = (
        await session.execute(select(AgentRun).where(AgentRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise AgentRuntimeError("run_not_found", f"agent_run {run_id} does not exist")
    return run


async def _load_agent(session: AsyncSession, agent_id: UUID) -> Agent:
    agent = (
        await session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise AgentRuntimeError("agent_not_found", f"agent {agent_id} does not exist")
    return agent


async def _find_step(
    session: AsyncSession, run_id: UUID, *, kind: str
) -> AgentStep | None:
    """The earliest journal boundary of ``kind`` for this run, or None — the
    replay primitive: 'has this boundary already happened?'."""
    return (
        await session.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run_id, AgentStep.kind == kind)
            .order_by(AgentStep.idx)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _append_step(
    session: AsyncSession,
    run: AgentRun,
    *,
    kind: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> AgentStep:
    """Append the next journal boundary at ``run.next_step_idx`` and advance the cursor.

    ``UNIQUE(run_id, idx)`` + the advancing cursor keep the journal strictly
    ordered and replay-safe; ``heartbeat_at`` is bumped so the OOM/SIGKILL
    backstop (``recover_stuck_agent_runs``) sees liveness.
    """
    step = AgentStep(
        run_id=run.id,
        idx=run.next_step_idx,
        kind=kind,
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    session.add(step)
    run.next_step_idx += 1
    run.heartbeat_at = _now()
    await session.flush()
    return step


def _should_skip(agent: Agent, run: AgentRun) -> bool:
    """Skip-when-nothing-changed: this wake's fingerprint matches the last success."""
    return run.content_hash is not None and run.content_hash == agent.content_hash


async def run_job(
    session: AsyncSession, run_id: UUID, *, planner: Planner
) -> AgentRun:
    """Replay + advance one agent run. Idempotent across re-delivery / resume.

    Returns the (possibly mutated) ``AgentRun``. The caller owns the transaction
    boundary (commit on success) — this function only flushes so its writes are
    visible within the session.
    """
    run = await _load_run(session, run_id)

    # A redelivered wake of a finished run does nothing (trigger_key UNIQUE means
    # this is the same run, not a fork).
    if run.status in TERMINAL_STATUSES:
        return run

    agent = await _load_agent(session, run.agent_id)

    # Skip-when-nothing-changed — journal the decision, terminate as skipped.
    if _should_skip(agent, run):
        await _append_step(
            session,
            run,
            kind="skip",
            payload={"reason": "unchanged", "content_hash": run.content_hash},
        )
        run.status = "skipped"
        run.finished_at = _now()
        await session.flush()
        return run

    # PLAN — journalled exactly once. On a resume the plan boundary already exists,
    # so we replay it instead of calling the planner again (never re-plan/fork).
    if await _find_step(session, run.id, kind="plan") is None:
        run.status = "planning"
        if run.started_at is None:
            run.started_at = _now()
        plan = await planner(agent, run)
        await _append_step(
            session,
            run,
            kind="plan",
            payload={"plan": plan.plan, "done_spec": plan.done_spec},
        )
        run.plan = plan.plan
        run.done_spec = plan.done_spec
        run.status = "running"
        await session.flush()

    return run
