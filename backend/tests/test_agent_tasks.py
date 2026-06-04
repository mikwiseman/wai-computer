"""Celery task orchestration for autonomous agents."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import companion_actions as ca
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.companion import Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.user import User
from app.tasks import agents as agent_tasks

pytestmark = pytest.mark.asyncio


async def test_dispatch_due_agents_commits_before_enqueue(db_session, monkeypatch):
    user = User(email=f"agent-cron-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(
        user_id=user.id,
        name="Scheduled",
        kind="digest",
        trigger_type="cron",
        enabled=True,
        config={"interval_minutes": 15},
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(agent)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    dispatched: list[str] = []

    def fake_delay(run_id: str) -> None:
        assert not db_session.in_transaction()
        dispatched.append(run_id)

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.run, "delay", fake_delay)

    count = await agent_tasks._dispatch_due_agents_async(limit=10)

    assert count == 1
    assert len(dispatched) == 1
    run = (
        await db_session.execute(
            select(AgentRun).where(AgentRun.id == UUID(dispatched[0]))
        )
    ).scalar_one()
    assert run.agent_id == agent.id
    assert run.status == "pending"
    await db_session.refresh(agent)
    assert agent.last_run_at is not None
    assert agent.next_run_at is not None
    assert agent.next_run_at > datetime.now(timezone.utc)


async def test_dispatch_due_agents_marks_run_failed_when_enqueue_fails(
    db_session, monkeypatch
):
    user = User(email=f"agent-cron-fail-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(
        user_id=user.id,
        name="Scheduled",
        kind="digest",
        trigger_type="cron",
        enabled=True,
        config={"interval_minutes": 15},
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(agent)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    def fail_delay(_run_id: str) -> None:
        raise RuntimeError("broker down")

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.run, "delay", fail_delay)

    count = await agent_tasks._dispatch_due_agents_async(limit=10)

    assert count == 0
    run = (
        await db_session.execute(select(AgentRun).where(AgentRun.agent_id == agent.id))
    ).scalar_one()
    assert run.status == "failed"
    assert run.error == "Could not enqueue agent run: RuntimeError"
    await db_session.refresh(agent)
    assert agent.last_run_at is None
    assert agent.next_run_at <= datetime.now(timezone.utc)


async def test_next_run_at_rejects_missing_invalid_and_non_positive_intervals():
    now = datetime(2026, 6, 3, tzinfo=timezone.utc)
    agent = Agent(config={})
    assert agent_tasks._next_run_at(agent, now) is None

    agent.config = {"interval_minutes": "bad"}
    assert agent_tasks._next_run_at(agent, now) is None

    agent.config = {"interval_minutes": 0}
    assert agent_tasks._next_run_at(agent, now) is None

    agent.config = {"interval_minutes": "15"}
    assert agent_tasks._next_run_at(agent, now) == now + timedelta(minutes=15)


async def test_run_agent_async_missing_run_raises(db_session, monkeypatch):
    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)

    with pytest.raises(RuntimeError, match="agent run not found"):
        await agent_tasks._run_agent_async(str(uuid4()))


async def test_run_agent_async_marks_failed_when_halted(db_session, monkeypatch):
    user = User(email=f"halted-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Halted", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.agent_guard, "agents_halted", AsyncMock(return_value=True))

    assert await agent_tasks._run_agent_async(str(run.id)) == "failed"
    assert run.status == "failed"
    assert run.error == "Agents are halted"


async def test_run_agent_async_budget_failure_and_slot_defer(db_session, monkeypatch):
    user = User(email=f"budget-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Budget", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    budget_run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
    )
    slot_run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
    )
    db_session.add_all([budget_run, slot_run])
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    async def raise_budget(_user_id: str) -> None:
        raise agent_tasks.agent_guard.AgentGuardError("user_runs", "budget blocked")

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.agent_guard, "agents_halted", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_tasks.agent_guard, "check_run_budget", raise_budget)

    assert await agent_tasks._run_agent_async(str(budget_run.id)) == "failed"
    assert budget_run.status == "failed"
    assert budget_run.error == "budget blocked"

    async def allow_budget(_user_id: str) -> None:
        return None

    monkeypatch.setattr(agent_tasks.agent_guard, "check_run_budget", allow_budget)
    monkeypatch.setattr(
        agent_tasks.agent_guard, "acquire_run_slot", AsyncMock(return_value=None)
    )

    assert await agent_tasks._run_agent_async(str(slot_run.id)) == "deferred"
    assert slot_run.status == "pending"
    assert slot_run.error == "Too many concurrent agent runs"


async def test_run_agent_async_success_releases_slot(db_session, monkeypatch):
    user = User(email=f"success-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Success", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()
    released: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    async def fake_run_job(db, run_id, *, planner, executor):
        assert db is db_session
        assert run_id == run.id
        assert planner is agent_tasks.static_config_planner
        assert executor is agent_tasks.execute_agent_step
        run.status = "done"
        return run

    async def fake_release(user_id: str, lease: str) -> None:
        released.append((user_id, lease))

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.agent_guard, "agents_halted", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_tasks.agent_guard, "check_run_budget", AsyncMock())
    monkeypatch.setattr(
        agent_tasks.agent_guard, "acquire_run_slot", AsyncMock(return_value="lease-1")
    )
    monkeypatch.setattr(agent_tasks.agent_guard, "record_run", AsyncMock())
    monkeypatch.setattr(agent_tasks.agent_guard, "release_run_slot", fake_release)
    monkeypatch.setattr(agent_tasks, "run_job", fake_run_job)

    assert await agent_tasks._run_agent_async(str(run.id)) == "done"
    assert released == [(str(user.id), "lease-1")]


async def test_celery_task_wrappers_delegate_to_asyncio_run(monkeypatch):
    calls: list[object] = []

    def fake_asyncio_run(coro):
        calls.append(coro)
        coro.close()
        return f"result-{len(calls)}"

    async def fake_run_agent_async(run_id: str) -> str:
        return f"run:{run_id}"

    async def fake_dispatch_due_agents_async(*, limit: int) -> int:
        return limit

    async def fake_recover_stale_agent_runs_async(*, limit: int) -> int:
        return limit

    async def fake_expire_due_actions_async() -> int:
        return 1

    monkeypatch.setattr(agent_tasks.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(agent_tasks, "_run_agent_async", fake_run_agent_async)
    monkeypatch.setattr(
        agent_tasks, "_dispatch_due_agents_async", fake_dispatch_due_agents_async
    )
    monkeypatch.setattr(
        agent_tasks,
        "_recover_stale_agent_runs_async",
        fake_recover_stale_agent_runs_async,
    )
    monkeypatch.setattr(agent_tasks, "_expire_due_actions_async", fake_expire_due_actions_async)

    assert agent_tasks.run("run-1") == "result-1"
    assert agent_tasks.dispatch_due_agents(limit=3) == "result-2"
    assert agent_tasks.recover_stale_agent_runs(limit=4) == "result-3"
    assert agent_tasks.expire_due_action_rows() == "result-4"
    assert len(calls) == 4


async def test_recover_stale_agent_runs_dispatches_old_rows_once(db_session, monkeypatch):
    user = User(email=f"recover-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Recover", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    stale = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="running",
        heartbeat_at=datetime.now(timezone.utc)
        - timedelta(seconds=agent_tasks.STALE_AFTER_SECONDS + 10),
    )
    old_pending = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="pending",
        created_at=datetime.now(timezone.utc)
        - timedelta(seconds=agent_tasks.STALE_AFTER_SECONDS + 20),
    )
    fresh = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="running",
        heartbeat_at=datetime.now(timezone.utc),
    )
    fresh_pending = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([stale, old_pending, fresh, fresh_pending])
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    dispatched: list[str] = []
    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.run, "delay", lambda run_id: dispatched.append(run_id))

    assert await agent_tasks._recover_stale_agent_runs_async(limit=10) == 2
    assert set(dispatched) == {str(stale.id), str(old_pending.id)}
    await db_session.refresh(stale)
    await db_session.refresh(old_pending)
    assert stale.heartbeat_at is not None
    assert old_pending.heartbeat_at is not None

    dispatched.clear()
    assert await agent_tasks._recover_stale_agent_runs_async(limit=10) == 0
    assert dispatched == []


async def test_recover_stale_agent_runs_marks_enqueue_failures(
    db_session, monkeypatch
):
    user = User(email=f"recover-fail-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Recover fail", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    stale = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="running",
        heartbeat_at=datetime.now(timezone.utc)
        - timedelta(seconds=agent_tasks.STALE_AFTER_SECONDS + 10),
    )
    db_session.add(stale)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    def fail_delay(_run_id: str) -> None:
        raise RuntimeError("broker offline")

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.run, "delay", fail_delay)

    assert await agent_tasks._recover_stale_agent_runs_async(limit=10) == 0
    await db_session.refresh(stale)
    assert stale.status == "failed"
    assert stale.error == "Could not enqueue stale agent run: RuntimeError"


async def test_expire_due_actions_task_expires_approved_queue_rows(
    db_session, monkeypatch
):
    user = User(email=f"agent-expire-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    row = await ca.propose_action(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "mailto:anna@example.com"},
        preview="Open a new email",
        idempotency_key=f"k-{uuid4().hex}",
    )
    row.status = "approved"
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)

    count = await agent_tasks._expire_due_actions_async()

    assert count >= 1
    await db_session.refresh(row)
    assert row.status == "expired"


async def test_expire_due_actions_task_resumes_agent_runs_as_failed(
    db_session, monkeypatch
):
    user = User(email=f"agent-expire-run-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(
        user_id=user.id,
        name="Needs approval",
        kind="approval",
        trigger_type="manual",
        config={
            "steps": [
                {
                    "tool": "propose_action",
                    "args": {
                        "kind": "send",
                        "tool_name": "send_message_telegram",
                        "action_args": {"text": "hello"},
                        "preview": "Send hello",
                    },
                }
            ]
        },
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{agent.id}:{uuid4().hex}",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()
    await agent_tasks.run_job(
        db_session,
        run.id,
        planner=agent_tasks.static_config_planner,
        executor=agent_tasks.execute_agent_step,
    )
    assert run.status == "awaiting_approval"
    action = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.agent_run_id == run.id
            )
        )
    ).scalar_one()
    action.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)

    count = await agent_tasks._expire_due_actions_async()

    assert count >= 1
    await db_session.refresh(run)
    await db_session.refresh(action)
    assert action.status == "expired"
    assert run.status == "failed"
    assert run.error == "Approval expired"
    steps = (
        await db_session.execute(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.idx)
        )
    ).scalars().all()
    assert [step.kind for step in steps][-2:] == ["approval_result", "error"]
