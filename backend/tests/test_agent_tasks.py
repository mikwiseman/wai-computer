"""Celery task orchestration for autonomous agents."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core import companion_actions as ca
from app.core.agent_runtime import static_config_planner
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
        assert planner is static_config_planner
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


async def test_run_task_retries_retryable_provider_errors(monkeypatch):
    async def fail_run_agent_async(_run_id: str) -> str:
        raise httpx.TimeoutException("provider timeout")

    def fake_asyncio_run(coro):
        coro.close()
        raise httpx.TimeoutException("provider timeout")

    monkeypatch.setattr(agent_tasks, "_run_agent_async", fail_run_agent_async)
    monkeypatch.setattr(agent_tasks.asyncio, "run", fake_asyncio_run)

    def fake_retry(*, exc):
        raise RuntimeError(f"retry requested: {type(exc).__name__}")

    monkeypatch.setattr(agent_tasks.run, "retry", fake_retry)

    with pytest.raises(RuntimeError, match="retry requested: TimeoutException"):
        agent_tasks.run.run("00000000-0000-0000-0000-000000000031")


async def test_run_task_retries_committed_retrying_status(monkeypatch):
    async def retrying_run_agent_async(_run_id: str) -> str:
        return "retrying"

    def fake_asyncio_run(coro):
        coro.close()
        return "retrying"

    monkeypatch.setattr(agent_tasks, "_run_agent_async", retrying_run_agent_async)
    monkeypatch.setattr(agent_tasks.asyncio, "run", fake_asyncio_run)

    def fake_retry(*, exc):
        raise RuntimeError(f"retry requested: {type(exc).__name__}")

    monkeypatch.setattr(agent_tasks.run, "retry", fake_retry)

    with pytest.raises(RuntimeError, match="retry requested: AgentRunRetryRequestedError"):
        agent_tasks.run.run("00000000-0000-0000-0000-000000000032")


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
    stale_planning_without_heartbeat = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="planning",
        created_at=datetime.now(timezone.utc)
        - timedelta(seconds=agent_tasks.STALE_AFTER_SECONDS + 30),
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
    db_session.add_all(
        [stale, old_pending, stale_planning_without_heartbeat, fresh, fresh_pending]
    )
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    dispatched: list[str] = []
    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.run, "delay", lambda run_id: dispatched.append(run_id))

    assert await agent_tasks._recover_stale_agent_runs_async(limit=10) == 3
    assert set(dispatched) == {
        str(stale.id),
        str(old_pending.id),
        str(stale_planning_without_heartbeat.id),
    }
    await db_session.refresh(stale)
    await db_session.refresh(old_pending)
    await db_session.refresh(stale_planning_without_heartbeat)
    assert stale.heartbeat_at is not None
    assert old_pending.heartbeat_at is not None
    assert stale_planning_without_heartbeat.heartbeat_at is not None

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
        planner=static_config_planner,
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


class _FakeResult:
    """Scripted substitute for a SQLAlchemy execute() result."""

    def __init__(self, *, rows: list[tuple] | None = None, scalar: object = None) -> None:
        self._rows = rows if rows is not None else []
        self._scalar = scalar

    def all(self) -> list[tuple]:
        return self._rows

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _FakeDb:
    """Minimal AsyncSession stand-in returning one scripted result per execute()."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)

    async def execute(self, _stmt) -> _FakeResult:
        return self._results.pop(0)


async def test_mark_retryable_failure_after_retries_marks_only_active_runs(
    db_session, monkeypatch
):
    user = User(email=f"retry-exhaust-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Retry", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    active = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="running",
    )
    done = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="done",
    )
    db_session.add_all([active, done])
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)

    await agent_tasks._mark_retryable_failure_after_retries(str(active.id))
    await agent_tasks._mark_retryable_failure_after_retries(str(done.id))
    await agent_tasks._mark_retryable_failure_after_retries(str(uuid4()))

    assert active.status == "failed"
    assert active.error == "Agent run failed after retryable provider errors."
    assert active.finished_at is not None
    assert done.status == "done"
    assert done.error is None


async def test_dispatch_child_runs_after_commit_enqueues_each_child(monkeypatch):
    dispatched: list[str] = []
    monkeypatch.setattr(agent_tasks.run, "delay", lambda run_id: dispatched.append(run_id))

    child_ids = [uuid4(), uuid4()]
    await agent_tasks._dispatch_child_runs_after_commit(child_ids)

    assert dispatched == [str(child_ids[0]), str(child_ids[1])]


async def test_dispatch_child_runs_after_commit_marks_enqueue_failures(
    db_session, monkeypatch
):
    user = User(email=f"child-fail-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    agent = Agent(user_id=user.id, name="Child", kind="manual", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    child = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
    )
    db_session.add(child)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    def fail_delay(_run_id: str) -> None:
        raise RuntimeError("broker down")

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.run, "delay", fail_delay)

    # The unknown id exercises the run-row-missing path; the real child run
    # must be marked failed so it is not silently lost.
    await agent_tasks._dispatch_child_runs_after_commit([child.id, uuid4()])

    assert child.status == "failed"
    assert child.error == "Could not enqueue delegated agent run: RuntimeError"


async def test_run_agent_async_marks_failed_when_agent_missing(monkeypatch):
    run = AgentRun(
        id=uuid4(),
        agent_id=uuid4(),
        user_id=uuid4(),
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="pending",
    )
    released: list[tuple[str, str]] = []

    @asynccontextmanager
    async def fake_db_context():
        yield _FakeDb(
            [
                _FakeResult(scalar=run),  # AgentRun lookup
                _FakeResult(scalar=None),  # Agent lookup → deleted/missing
            ]
        )

    async def fake_release(user_id: str, lease: str) -> None:
        released.append((user_id, lease))

    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks.agent_guard, "agents_halted", AsyncMock(return_value=False))
    monkeypatch.setattr(agent_tasks.agent_guard, "check_run_budget", AsyncMock())
    monkeypatch.setattr(
        agent_tasks.agent_guard, "acquire_run_slot", AsyncMock(return_value="lease-9")
    )
    monkeypatch.setattr(agent_tasks.agent_guard, "record_run", AsyncMock())
    monkeypatch.setattr(agent_tasks.agent_guard, "release_run_slot", fake_release)

    assert await agent_tasks._run_agent_async(str(run.id)) == "failed"
    assert run.status == "failed"
    assert run.error == "Agent not found"
    assert released == [(str(run.user_id), "lease-9")]


async def test_run_task_raises_non_retryable_errors(monkeypatch):
    def fake_asyncio_run(coro):
        coro.close()
        raise ValueError("invalid agent config")

    retried: list[Exception] = []
    monkeypatch.setattr(agent_tasks.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(agent_tasks.run, "retry", lambda *, exc: retried.append(exc))

    with pytest.raises(ValueError, match="invalid agent config"):
        agent_tasks.run.run(str(uuid4()))

    assert retried == []


async def test_run_task_marks_run_failed_when_retries_exhausted(monkeypatch):
    consumed: list[str] = []

    def fake_asyncio_run(coro):
        consumed.append(coro.__qualname__)
        coro.close()
        if len(consumed) == 1:
            raise httpx.TimeoutException("provider timeout")
        return None

    def fail_retry(*, exc):
        raise AssertionError("retry must not be requested once retries are exhausted")

    monkeypatch.setattr(agent_tasks.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(agent_tasks.run, "retry", fail_retry)
    monkeypatch.setattr(agent_tasks.run, "max_retries", 0)

    with pytest.raises(httpx.TimeoutException, match="provider timeout"):
        agent_tasks.run.run(str(uuid4()))

    assert consumed == ["_run_agent_async", "_mark_retryable_failure_after_retries"]


async def test_expire_due_actions_task_marks_run_failed_when_agent_missing(monkeypatch):
    run = AgentRun(
        id=uuid4(),
        agent_id=uuid4(),
        user_id=uuid4(),
        trigger_key=f"manual:{uuid4()}",
        trigger_kind="manual",
        status="awaiting_approval",
    )

    @asynccontextmanager
    async def fake_db_context():
        yield _FakeDb(
            [
                _FakeResult(rows=[(run.id,)]),  # due pending-action run ids
                _FakeResult(scalar=run),  # awaiting_approval run lookup
                _FakeResult(scalar=None),  # Agent lookup → deleted/missing
            ]
        )

    async def fake_expire(db, *, now):
        return 4

    run_job_mock = AsyncMock()
    monkeypatch.setattr(agent_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(agent_tasks, "expire_due_actions", fake_expire)
    monkeypatch.setattr(agent_tasks, "run_job", run_job_mock)

    assert await agent_tasks._expire_due_actions_async() == 4
    assert run.status == "failed"
    assert run.error == "Agent not found"
    run_job_mock.assert_not_awaited()
