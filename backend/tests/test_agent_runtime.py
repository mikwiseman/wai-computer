"""Stateless journalled harness (P6 ``agent_runtime``) — replay + plan/skip slice.

Pins the load-bearing guarantees the durable journal exists for:
* a fresh run PLANS once and journals the boundary;
* a re-delivered / resumed run REPLAYS — it never re-plans or forks a step;
* skip-when-nothing-changed short-circuits with a journalled ``skip``;
* a finished run is an idempotent no-op (re-delivery is safe);
* a missing run SURFACES an error (no silent fallback).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.agent_runtime import AgentPlan, AgentRuntimeError, run_job
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def user(db_session) -> User:
    u = User(email=f"agent-rt-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    return u


async def _agent_and_run(db_session, user, **run_kwargs) -> tuple[Agent, AgentRun]:
    agent = Agent(
        user_id=user.id,
        name="Friday reminder",
        kind="commitments_friday_reminder",
        trigger_type="cron",
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"cron:{agent.id}:{uuid4().hex}",
        trigger_kind="cron",
        **run_kwargs,
    )
    db_session.add(run)
    await db_session.flush()
    return agent, run


def _counting_planner(plan: dict, done_spec: dict):
    """A fake planner that records how many times it was invoked."""
    calls = {"n": 0}

    async def planner(agent: Agent, run: AgentRun) -> AgentPlan:
        calls["n"] += 1
        return AgentPlan(plan=plan, done_spec=done_spec)

    return planner, calls


async def _steps(db_session, run_id) -> list[AgentStep]:
    result = await db_session.execute(
        select(AgentStep)
        .where(AgentStep.run_id == run_id)
        .order_by(AgentStep.idx)
    )
    return list(result.scalars().all())


async def test_run_job_plans_a_fresh_run(db_session, user) -> None:
    _, run = await _agent_and_run(db_session, user)
    planner, calls = _counting_planner(
        {"steps": ["check_commitments"]}, {"check": "sent"}
    )

    await run_job(db_session, run.id, planner=planner)
    await db_session.refresh(run)

    assert calls["n"] == 1
    assert run.status == "running"
    assert run.plan == {"steps": ["check_commitments"]}
    assert run.done_spec == {"check": "sent"}
    assert run.next_step_idx == 1
    assert run.started_at is not None

    steps = await _steps(db_session, run.id)
    assert [s.kind for s in steps] == ["plan"]
    assert steps[0].idx == 0
    assert steps[0].payload["plan"] == {"steps": ["check_commitments"]}
    assert steps[0].payload["done_spec"] == {"check": "sent"}


async def test_run_job_replays_without_replanning(db_session, user) -> None:
    _, run = await _agent_and_run(db_session, user)
    planner, calls = _counting_planner({"steps": []}, {})

    await run_job(db_session, run.id, planner=planner)
    await run_job(db_session, run.id, planner=planner)  # resume / redelivery
    await db_session.refresh(run)

    # Planned once; the second pass replayed the journal instead of re-planning.
    assert calls["n"] == 1
    steps = await _steps(db_session, run.id)
    assert [s.kind for s in steps] == ["plan"]  # never forked a duplicate plan
    assert run.next_step_idx == 1


async def test_run_job_skips_when_content_unchanged(db_session, user) -> None:
    agent, run = await _agent_and_run(db_session, user, content_hash="sha-abc")
    agent.content_hash = "sha-abc"  # last success had the identical fingerprint
    await db_session.flush()
    planner, calls = _counting_planner({"steps": ["x"]}, {})

    await run_job(db_session, run.id, planner=planner)
    await db_session.refresh(run)

    assert calls["n"] == 0  # nothing changed → no planning, no work
    assert run.status == "skipped"
    assert run.finished_at is not None
    steps = await _steps(db_session, run.id)
    assert [s.kind for s in steps] == ["skip"]
    assert steps[0].payload["reason"] == "unchanged"


async def test_run_job_is_noop_on_terminal_run(db_session, user) -> None:
    _, run = await _agent_and_run(db_session, user)
    run.status = "done"
    await db_session.flush()
    planner, calls = _counting_planner({"steps": ["x"]}, {})

    result = await run_job(db_session, run.id, planner=planner)

    assert result.status == "done"
    assert calls["n"] == 0
    assert await _steps(db_session, run.id) == []


async def test_run_job_surfaces_missing_run(db_session, user) -> None:
    planner, _ = _counting_planner({}, {})
    with pytest.raises(AgentRuntimeError) as exc:
        await run_job(db_session, uuid4(), planner=planner)
    assert exc.value.code == "run_not_found"
