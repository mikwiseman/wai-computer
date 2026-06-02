"""Schema invariants for the working-agents durable journal (P6 substrate).

These pin the load-bearing guarantees the stateless harness relies on:
* server-side defaults (autonomy=propose, enabled, status=pending, idx cursor);
* ``trigger_key`` UNIQUE — a redelivered wake can NEVER fork a second run;
* ``UNIQUE(run_id, idx)`` — the append-only journal stays strictly ordered;
* FK cascade — deleting an agent reaps its runs and their steps.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.agent import Agent, AgentRun, AgentStep
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def user(db_session) -> User:
    u = User(email=f"agent-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    return u


async def _run(db_session, user, *, trigger_key: str) -> AgentRun:
    agent = Agent(
        user_id=user.id, name="Friday reminder",
        kind="commitments_friday_reminder", trigger_type="cron",
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id, user_id=user.id,
        trigger_key=trigger_key, trigger_kind="cron",
    )
    db_session.add(run)
    await db_session.flush()
    return run


async def test_agent_run_step_roundtrip_defaults(db_session, user) -> None:
    agent = Agent(
        user_id=user.id, name="Friday reminder",
        kind="commitments_friday_reminder", trigger_type="cron",
    )
    db_session.add(agent)
    await db_session.flush()
    await db_session.refresh(agent)
    # v1 autonomy ceiling + sane defaults come from the DB, not the caller.
    assert agent.autonomy == "propose"
    assert agent.enabled is True
    assert agent.config == {}

    run = AgentRun(
        agent_id=agent.id, user_id=user.id,
        trigger_key=f"cron:{agent.id}:2026-W23", trigger_kind="cron",
    )
    db_session.add(run)
    await db_session.flush()
    await db_session.refresh(run)
    assert run.status == "pending"
    assert run.next_step_idx == 0

    step = AgentStep(run_id=run.id, idx=0, kind="plan")
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)
    assert step.payload == {}
    assert step.idempotency_key is None


async def test_trigger_key_is_unique(db_session, user) -> None:
    # The redelivery-resume invariant: one wake => at most one run.
    await _run(db_session, user, trigger_key="cron:dup:2026-W23")
    dupe_agent = Agent(
        user_id=user.id, name="x", kind="commitments_friday_reminder",
        trigger_type="cron",
    )
    db_session.add(dupe_agent)
    await db_session.flush()
    db_session.add(
        AgentRun(
            agent_id=dupe_agent.id, user_id=user.id,
            trigger_key="cron:dup:2026-W23", trigger_kind="cron",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_step_run_idx_is_unique(db_session, user) -> None:
    run = await _run(db_session, user, trigger_key="cron:idx:2026-W23")
    db_session.add(AgentStep(run_id=run.id, idx=0, kind="plan"))
    await db_session.flush()
    db_session.add(AgentStep(run_id=run.id, idx=0, kind="tool_call"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_cascade_delete_agent_reaps_runs_and_steps(db_session, user) -> None:
    run = await _run(db_session, user, trigger_key="cron:cascade:2026-W23")
    db_session.add(AgentStep(run_id=run.id, idx=0, kind="final"))
    await db_session.flush()
    agent_id = run.agent_id

    agent = (
        await db_session.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one()
    await db_session.delete(agent)
    await db_session.flush()

    runs = (
        await db_session.execute(
            select(AgentRun).where(AgentRun.agent_id == agent_id)
        )
    ).scalars().all()
    steps = (
        await db_session.execute(
            select(AgentStep).where(AgentStep.run_id == run.id)
        )
    ).scalars().all()
    assert runs == []  # FK cascade reaped the run...
    assert steps == []  # ...and its journal steps.


async def test_step_idempotency_key_persists(db_session, user) -> None:
    run = await _run(db_session, user, trigger_key="cron:idem:2026-W23")
    key = f"{run.id}:1:send_message_telegram"
    step = AgentStep(
        run_id=run.id, idx=1, kind="approval_request",
        payload={"tool": "send_message_telegram"}, idempotency_key=key,
    )
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)
    assert step.idempotency_key == key
    assert step.payload["tool"] == "send_message_telegram"
