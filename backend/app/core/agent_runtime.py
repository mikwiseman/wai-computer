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

Plan-then-execute: a planner produces a plan + ``done_spec`` exactly once
(journalled), execution appends ``tool_call`` / ``tool_result`` boundaries, and a
verifier checks the ``done_spec`` before ``final``. Mutating tools never run
inline: they create a pending approval row and the runtime resumes only after the
approval gate records a receipt.

Privacy: plan/step payloads MAY carry recipient/body — they stay in Postgres and
are NEVER logged raw (AGENTS.md).
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_capabilities import (
    ACTION_TOOL_NAMES,
    DESKTOP_ACTION_TOOL_NAMES,
    MAX_AGENT_SEARCH_LIMIT,
    MAX_AGENT_STEPS,
    validate_agent_config,
)
from app.core.companion_actions import DEFAULT_TTL_SECONDS, expire_actions_for_run, propose_action
from app.core.memory_proposal import propose_block_update
from app.core.unified_search import unified_search
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item, ItemChunk

AGENT_RUNS_TO_DISPATCH_SESSION_KEY = "agent_runs_to_dispatch_after_commit"

# A run in one of these states is finished — run_job is a no-op (safe re-delivery).
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"done", "failed", "expired", "skipped", "cancelled"}
)
WAITING_APPROVAL_STATUSES: frozenset[str] = frozenset({"pending", "approved"})


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


@dataclass(frozen=True)
class AgentStepResult:
    """Result of executing one planned step.

    ``status='awaiting_approval'`` means the side effect has not happened and
    the runtime must stop until the approval ledger has a terminal receipt.
    """

    status: str
    payload: dict[str, Any]


# Injectable planner. Real impl = a bounded Haiku-class LLM call; tests pass a fake.
Planner = Callable[[Agent, AgentRun], Awaitable[AgentPlan]]
Executor = Callable[
    [AsyncSession, Agent, AgentRun, dict[str, Any], int, str],
    Awaitable[AgentStepResult],
]
Verifier = Callable[[AsyncSession, Agent, AgentRun], Awaitable[dict[str, Any]]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def pop_agent_runs_to_dispatch_after_commit(session: AsyncSession) -> list[UUID]:
    """Return and clear child run ids that must be enqueued after commit."""
    values = session.sync_session.info.pop(AGENT_RUNS_TO_DISPATCH_SESSION_KEY, [])
    return list(values)


def _queue_agent_run_after_commit(session: AsyncSession, run_id: UUID) -> None:
    queued = session.sync_session.info.setdefault(
        AGENT_RUNS_TO_DISPATCH_SESSION_KEY, []
    )
    if run_id not in queued:
        queued.append(run_id)


async def _load_run(session: AsyncSession, run_id: UUID) -> AgentRun:
    stmt = select(AgentRun).where(AgentRun.id == run_id)
    bind = session.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
        stmt = stmt.with_for_update()
    run = (await session.execute(stmt)).scalar_one_or_none()
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
    session: AsyncSession,
    run_id: UUID,
    *,
    kind: str,
    idempotency_key: str | None = None,
) -> AgentStep | None:
    """The earliest journal boundary of ``kind`` for this run, or None — the
    replay primitive: 'has this boundary already happened?'."""
    stmt = select(AgentStep).where(AgentStep.run_id == run_id, AgentStep.kind == kind)
    if idempotency_key is not None:
        stmt = stmt.where(AgentStep.idempotency_key == idempotency_key)
    return (await session.execute(stmt.order_by(AgentStep.idx).limit(1))).scalar_one_or_none()


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


def _step_tool_and_args(step: dict[str, Any], idx: int) -> tuple[str, dict[str, Any]]:
    if not isinstance(step, dict):
        raise AgentRuntimeError(
            "invalid_plan_step", f"plan.steps[{idx}] must be an object"
        )
    tool = step.get("tool")
    args = step.get("args") or {}
    if not isinstance(tool, str) or not tool:
        raise AgentRuntimeError(
            "invalid_plan_step", f"plan.steps[{idx}].tool must be a non-empty string"
        )
    if not isinstance(args, dict):
        raise AgentRuntimeError(
            "invalid_plan_step", f"plan.steps[{idx}].args must be an object"
        )
    return tool, args


def _plan_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = plan.get("steps")
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise AgentRuntimeError("invalid_plan", "plan.steps must be an array")
    if len(steps) > MAX_AGENT_STEPS:
        raise AgentRuntimeError(
            "invalid_plan",
            f"plan.steps cannot exceed {MAX_AGENT_STEPS} steps",
        )
    return steps


def _tool_call_key(run: AgentRun, plan_step_idx: int) -> str:
    return f"{run.id}:plan-step:{plan_step_idx}:tool_call"


def _effect_key(run: AgentRun, tool_call_idx: int, tool_name: str) -> str:
    return f"{run.id}:{tool_call_idx}:{tool_name}"


async def static_config_planner(agent: Agent, run: AgentRun) -> AgentPlan:
    """Plan from ``agent.config['steps']``.

    This is the deterministic v1 planner used by API-created template agents and
    tests. A future LLM planner can be swapped in without changing the journal,
    approval, or execution safety boundary.
    """
    try:
        validate_agent_config(agent.config or {})
    except ValueError as exc:
        raise AgentRuntimeError("invalid_agent_config", str(exc)) from exc
    steps = (agent.config or {}).get("steps")
    if not isinstance(steps, list):
        raise AgentRuntimeError(
            "missing_agent_steps",
            "Agent config must include a steps array before it can run",
        )
    done_spec = (agent.config or {}).get("done_spec")
    if done_spec is not None and not isinstance(done_spec, dict):
        raise AgentRuntimeError("invalid_done_spec", "Agent done_spec must be an object")
    return AgentPlan(
        plan={"steps": steps},
        done_spec=done_spec or {"mode": "all_steps_completed", "step_count": len(steps)},
    )


async def _find_pending_action_by_key(
    session: AsyncSession, idempotency_key: str
) -> CompanionPendingAction | None:
    return (
        await session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()


async def _resume_approval_if_ready(
    session: AsyncSession,
    run: AgentRun,
    *,
    effect_key: str,
) -> bool:
    """Return True when this step already has/now gained a tool_result.

    If the approval is still pending, set ``awaiting_approval`` and return
    False. Rejection/expiry/failure is terminal and recorded as an error.
    """
    if await _find_step(session, run.id, kind="tool_result", idempotency_key=effect_key):
        return True

    approval = await _find_step(
        session, run.id, kind="approval_request", idempotency_key=effect_key
    )
    if approval is None:
        return False

    row = await _find_pending_action_by_key(session, effect_key)
    if row is None:
        await _append_step(
            session,
            run,
            kind="error",
            payload={"code": "approval_row_missing", "idempotency_key": effect_key},
            idempotency_key=effect_key,
        )
        run.status = "failed"
        run.error = "Approval row missing"
        run.finished_at = _now()
        await session.flush()
        return False

    if row.status in WAITING_APPROVAL_STATUSES:
        run.status = "awaiting_approval"
        run.heartbeat_at = _now()
        await session.flush()
        return False

    await _append_step(
        session,
        run,
        kind="approval_result",
        payload={"action_id": str(row.id), "status": row.status, "receipt": row.receipt},
        idempotency_key=effect_key,
    )
    if row.status != "executed":
        run.status = "failed"
        run.error = f"Approval {row.status}"
        run.finished_at = _now()
        await _append_step(
            session,
            run,
            kind="error",
            payload={"code": "approval_not_executed", "status": row.status},
            idempotency_key=effect_key,
        )
        await session.flush()
        return False

    run.status = "running"
    run.heartbeat_at = _now()
    await _append_step(
        session,
        run,
        kind="tool_result",
        payload={"status": "executed", "receipt": row.receipt or {}},
        idempotency_key=effect_key,
    )
    return True


async def _default_verifier(
    session: AsyncSession, agent: Agent, run: AgentRun
) -> dict[str, Any]:
    steps = _plan_steps(run.plan or {})
    tool_results = (
        await session.execute(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.kind == "tool_result",
            )
        )
    ).scalars().all()
    return {
        "ok": len(tool_results) >= len(steps),
        "expected_steps": len(steps),
        "completed_steps": len(tool_results),
    }


def _content_hash(title: str, body: str, source_ref: str) -> str:
    return hashlib.sha256(
        f"agent\x00{source_ref}\x00{title}\x00{body}".encode("utf-8")
    ).hexdigest()


async def _create_artifact(
    session: AsyncSession,
    run: AgentRun,
    *,
    tool_call_idx: int,
    args: dict[str, Any],
) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    body = str(args.get("body") or "").strip()
    kind = str(args.get("kind") or "note").strip()
    if not title:
        raise AgentRuntimeError("invalid_tool_args", "create_artifact.title is required")
    if not body:
        raise AgentRuntimeError("invalid_tool_args", "create_artifact.body is required")
    if not kind:
        raise AgentRuntimeError("invalid_tool_args", "create_artifact.kind is required")
    source_ref = f"agent_run:{run.id}:step:{tool_call_idx}"
    existing = (
        await session.execute(
            select(Item).where(
                Item.user_id == run.user_id,
                Item.source == "agent",
                Item.source_ref == source_ref,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"item_id": str(existing.id), "created": False}

    item = Item(
        user_id=run.user_id,
        source="agent",
        source_ref=source_ref,
        kind=kind,
        title=title,
        body=body,
        content_hash=_content_hash(title, body, source_ref),
        authority_score=0.7,
        salience_score=0.5,
        metadata_={"agent_run_id": str(run.id), "agent_step_idx": tool_call_idx},
    )
    session.add(item)
    await session.flush()
    session.add(ItemChunk(item_id=item.id, seq=0, content=f"{title}\n\n{body}"))
    await session.flush()
    return {"item_id": str(item.id), "created": True}


def _delegate_trigger_key(idempotency_key: str) -> str:
    return f"agent:{idempotency_key}"


async def _load_delegate_target(
    session: AsyncSession,
    run: AgentRun,
    *,
    agent_id: str | None,
    agent_name: str | None,
) -> Agent:
    if agent_id is not None:
        try:
            target_id = UUID(agent_id)
        except ValueError as exc:
            raise AgentRuntimeError(
                "invalid_tool_args",
                "delegate_agent.agent_id must be a UUID string",
            ) from exc
        target = (
            await session.execute(
                select(Agent).where(
                    Agent.id == target_id,
                    Agent.user_id == run.user_id,
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise AgentRuntimeError(
                "invalid_tool_args",
                "delegate_agent target agent not found",
            )
        return target

    if agent_name is None:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent requires exactly one of agent_id or agent_name",
        )
    matches = list(
        (
            await session.execute(
                select(Agent)
                .where(Agent.user_id == run.user_id, Agent.name == agent_name)
                .order_by(Agent.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not matches:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent target agent not found",
        )
    if len(matches) > 1:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent target agent name is ambiguous",
        )
    return matches[0]


async def _delegate_agent(
    session: AsyncSession,
    agent: Agent,
    run: AgentRun,
    *,
    tool_call_idx: int,
    args: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    if run.parent_run_id is not None:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "Nested delegate_agent calls are not enabled yet",
        )
    objective = str(args.get("objective") or "").strip()
    if not objective:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent.objective is required",
        )
    raw_agent_id = str(args.get("agent_id") or "").strip() or None
    raw_agent_name = str(args.get("agent_name") or "").strip() or None
    if (raw_agent_id is None) == (raw_agent_name is None):
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent requires exactly one of agent_id or agent_name",
        )
    target = await _load_delegate_target(
        session,
        run,
        agent_id=raw_agent_id,
        agent_name=raw_agent_name,
    )
    if target.id == agent.id:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent cannot target the current agent",
        )
    if not target.enabled:
        raise AgentRuntimeError(
            "invalid_tool_args",
            "delegate_agent target agent is disabled",
        )

    trigger_key = _delegate_trigger_key(idempotency_key)
    existing = (
        await session.execute(
            select(AgentRun).where(
                AgentRun.user_id == run.user_id,
                AgentRun.trigger_key == trigger_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "child_run_id": str(existing.id),
            "agent_id": str(target.id),
            "status": existing.status,
            "created": False,
        }

    child = AgentRun(
        agent_id=target.id,
        user_id=run.user_id,
        trigger_key=trigger_key,
        trigger_kind="agent",
        trigger_payload={
            "objective": objective,
            "delegated_by_agent_id": str(agent.id),
            "delegated_by_run_id": str(run.id),
            "parent_step_idx": tool_call_idx,
        },
        parent_run_id=run.id,
        parent_step_idx=tool_call_idx,
    )
    session.add(child)
    await session.flush()
    _queue_agent_run_after_commit(session, child.id)
    return {
        "child_run_id": str(child.id),
        "agent_id": str(target.id),
        "status": child.status,
        "created": True,
    }


async def execute_agent_step(
    session: AsyncSession,
    agent: Agent,
    run: AgentRun,
    step: dict[str, Any],
    tool_call_idx: int,
    idempotency_key: str,
) -> AgentStepResult:
    """Execute the small first-party v1 tool vocabulary.

    External writes are represented only by ``propose_action``; the actual send
    or desktop action remains owned by the approval/actuator pipeline.
    """
    tool, args = _step_tool_and_args(step, tool_call_idx)

    if tool == "note":
        text = str(args.get("text") or "").strip()
        if not text:
            raise AgentRuntimeError("invalid_tool_args", "note.text is required")
        return AgentStepResult(status="done", payload={"text": text})

    if tool == "create_artifact":
        payload = await _create_artifact(
            session, run, tool_call_idx=tool_call_idx, args=args
        )
        return AgentStepResult(status="done", payload=payload)

    if tool == "search_wai":
        query = str(args.get("query") or "").strip()
        if not query:
            raise AgentRuntimeError("invalid_tool_args", "search_wai.query is required")
        raw_limit = args.get("limit", 10)
        if (
            not isinstance(raw_limit, int)
            or isinstance(raw_limit, bool)
            or raw_limit < 1
            or raw_limit > MAX_AGENT_SEARCH_LIMIT
        ):
            raise AgentRuntimeError(
                "invalid_tool_args",
                f"search_wai.limit must be 1..{MAX_AGENT_SEARCH_LIMIT}",
            )
        limit = raw_limit
        hits = await unified_search(session, run.user_id, query, limit=limit)
        return AgentStepResult(
            status="done",
            payload={
                "query": query,
                "hits": [
                    {
                        "source_kind": h.source_kind,
                        "parent_id": h.parent_id,
                        "chunk_id": h.chunk_id,
                        "title": h.title,
                        "kind": h.kind,
                        "snippet": h.snippet,
                        "score": h.score,
                        "created_at": h.created_at,
                    }
                    for h in hits
                ],
            },
        )

    if tool == "propose_memory":
        content = str(args.get("content") or "").strip()
        block = str(args.get("block") or "topics").strip()
        operation = str(args.get("operation") or "append").strip()
        if not content:
            raise AgentRuntimeError("invalid_tool_args", "propose_memory.content is required")
        outcome = await propose_block_update(
            session,
            run.user_id,
            block_label=block,
            operation=operation,
            content=content,
            target_line=args.get("target_line"),
            confidence=float(args.get("confidence") or 0.6),
            authority=str(args.get("authority") or "agent"),
            summary=args.get("summary"),
            evidence=args.get("evidence"),
        )
        if outcome is None:
            return AgentStepResult(status="done", payload={"proposal": "duplicate"})
        return AgentStepResult(
            status="done",
            payload={
                "proposal_id": str(outcome.proposal.id),
                "decision": outcome.decision,
                "status": outcome.proposal.status,
            },
        )

    if tool == "propose_action":
        existing = await _find_pending_action_by_key(session, idempotency_key)
        if existing is not None:
            return AgentStepResult(
                status="awaiting_approval",
                payload={"action_id": str(existing.id), "status": existing.status},
            )
        tool_name = str(args.get("tool_name") or "").strip()
        action_args = args.get("action_args") or {}
        preview = str(args.get("preview") or "").strip()
        if not tool_name:
            raise AgentRuntimeError("invalid_tool_args", "propose_action.tool_name is required")
        if tool_name not in ACTION_TOOL_NAMES:
            raise AgentRuntimeError(
                "invalid_tool_args", f"Unsupported action tool: {tool_name}"
            )
        kind = str(
            args.get("kind")
            or ("desktop_action" if tool_name in DESKTOP_ACTION_TOOL_NAMES else "mutate")
        ).strip()
        if not isinstance(action_args, dict):
            raise AgentRuntimeError(
                "invalid_tool_args",
                "propose_action.action_args must be an object",
            )
        if not preview:
            raise AgentRuntimeError("invalid_tool_args", "propose_action.preview is required")
        device_target = args.get("device_target")
        if tool_name in DESKTOP_ACTION_TOOL_NAMES:
            kind = "desktop_action"
        if tool_name in DESKTOP_ACTION_TOOL_NAMES and not device_target:
            raise AgentRuntimeError(
                "invalid_tool_args",
                "propose_action.device_target is required for desktop actions",
            )
        raw_ttl_seconds = args.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        if (
            not isinstance(raw_ttl_seconds, int)
            or isinstance(raw_ttl_seconds, bool)
            or raw_ttl_seconds < 1
            or raw_ttl_seconds > DEFAULT_TTL_SECONDS
        ):
            raise AgentRuntimeError(
                "invalid_tool_args",
                f"propose_action.ttl_seconds must be 1..{DEFAULT_TTL_SECONDS}",
            )
        row = await propose_action(
            session,
            user_id=run.user_id,
            conversation_id=None,
            agent_run_id=run.id,
            agent_step_idx=tool_call_idx,
            kind=kind,
            tool_name=tool_name,
            args=action_args,
            preview=preview,
            idempotency_key=idempotency_key,
            recipient_display=args.get("recipient_display"),
            device_target=device_target,
            ttl_seconds=raw_ttl_seconds,
        )
        return AgentStepResult(
            status="awaiting_approval",
            payload={
                "action_id": str(row.id),
                "tool": tool_name,
                "expires_at": row.expires_at.isoformat(),
            },
        )

    if tool == "delegate_agent":
        payload = await _delegate_agent(
            session,
            agent,
            run,
            tool_call_idx=tool_call_idx,
            args=args,
            idempotency_key=idempotency_key,
        )
        return AgentStepResult(status="done", payload=payload)

    raise AgentRuntimeError("unknown_agent_tool", f"Unknown agent tool: {tool}")


async def cancel_run(
    session: AsyncSession,
    run: AgentRun,
    *,
    reason: str | None = None,
) -> AgentRun:
    if run.status in TERMINAL_STATUSES:
        return run
    now = _now()
    run.cancel_requested_at = now
    await expire_actions_for_run(session, run_id=run.id, user_id=run.user_id, now=now)
    if await _find_step(session, run.id, kind="cancel") is None:
        await _append_step(
            session,
            run,
            kind="cancel",
            payload={"reason": reason or "cancelled"},
        )
    run.status = "cancelled"
    run.finished_at = now
    await session.flush()
    return run


async def run_job(
    session: AsyncSession,
    run_id: UUID,
    *,
    planner: Planner,
    executor: Executor | None = None,
    verifier: Verifier | None = None,
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
    if agent.user_id != run.user_id:
        raise AgentRuntimeError(
            "agent_run_user_mismatch",
            "Agent run user_id does not match its agent owner",
        )
    run.error = None

    if run.cancel_requested_at is not None:
        await cancel_run(session, run, reason="cancel requested")
        return run

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

    try:
        # PLAN — journalled exactly once. On a resume the plan boundary already
        # exists, so we replay it instead of calling the planner again.
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

        # Existing callers/tests can still use the plan-only harness by omitting
        # an executor.
        if executor is None:
            return run

        for plan_step_idx, step in enumerate(_plan_steps(run.plan or {})):
            tool_name, _ = _step_tool_and_args(step, plan_step_idx)
            tool_key = _tool_call_key(run, plan_step_idx)
            tool_call = await _find_step(
                session, run.id, kind="tool_call", idempotency_key=tool_key
            )
            if tool_call is None:
                tool_call = await _append_step(
                    session,
                    run,
                    kind="tool_call",
                    payload=step,
                    idempotency_key=tool_key,
                )
            effect_key = _effect_key(run, tool_call.idx, tool_name)

            if await _resume_approval_if_ready(session, run, effect_key=effect_key):
                continue
            if run.status in {"awaiting_approval", "failed"}:
                return run
            if await _find_step(
                session, run.id, kind="tool_result", idempotency_key=effect_key
            ):
                continue

            result = await executor(
                session, agent, run, step, tool_call.idx, effect_key
            )
            if result.status == "awaiting_approval":
                if await _find_step(
                    session,
                    run.id,
                    kind="approval_request",
                    idempotency_key=effect_key,
                ) is None:
                    await _append_step(
                        session,
                        run,
                        kind="approval_request",
                        payload=result.payload,
                        idempotency_key=effect_key,
                    )
                run.status = "awaiting_approval"
                await session.flush()
                return run
            if result.status != "done":
                raise AgentRuntimeError(
                    "invalid_executor_result",
                    f"Executor returned unknown status {result.status}",
                )
            await _append_step(
                session,
                run,
                kind="tool_result",
                payload=result.payload,
                idempotency_key=effect_key,
            )

        verifier = verifier or _default_verifier
        verify_step = await _find_step(session, run.id, kind="verify")
        if verify_step is None:
            verdict = await verifier(session, agent, run)
            verify_step = await _append_step(session, run, kind="verify", payload=verdict)
        verdict = verify_step.payload or {}
        if verdict.get("ok") is not True:
            run.status = "failed"
            run.error = "Agent verification failed"
            run.finished_at = _now()
            if await _find_step(session, run.id, kind="error") is None:
                await _append_step(
                    session,
                    run,
                    kind="error",
                    payload={"code": "verification_failed", "verdict": verdict},
                )
            await session.flush()
            return run
        if await _find_step(session, run.id, kind="final") is None:
            run.status = "done"
            run.result = {
                "status": "done",
                "completed_at": _now().isoformat(),
                "done_spec": run.done_spec or {},
            }
            run.finished_at = _now()
            agent.last_run_at = run.finished_at
            if run.content_hash:
                agent.content_hash = run.content_hash
            await _append_step(session, run, kind="final", payload=run.result)
        await session.flush()
        return run
    except AgentRuntimeError as exc:
        if await _find_step(session, run.id, kind="error") is None:
            await _append_step(
                session, run, kind="error", payload={"code": exc.code, "message": exc.message}
            )
        run.status = "failed"
        run.error = exc.message
        run.finished_at = _now()
        await session.flush()
        return run
    except Exception as exc:
        if await _find_step(session, run.id, kind="error") is None:
            await _append_step(
                session,
                run,
                kind="error",
                payload={"code": "unexpected_error", "message": type(exc).__name__},
            )
        run.status = "failed"
        run.error = f"Unexpected agent runtime error: {type(exc).__name__}"
        run.finished_at = _now()
        await session.flush()
        return run
