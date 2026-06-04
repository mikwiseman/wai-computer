"""Full autonomous-agent journal execution.

Pins the v1 runtime beyond the plan-only slice:
* static/configured plans execute internal tools through the journal;
* artifacts are persisted as Wai items with provenance;
* mutating actions stop at the approval gate and resume after execution;
* cancellation is journalled and terminal.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.agent_runtime import (
    AgentPlan,
    AgentRuntimeError,
    AgentStepResult,
    cancel_run,
    execute_agent_step,
    run_job,
    static_config_planner,
)
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def user(db_session) -> User:
    u = User(email=f"agent-exec-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    return u


async def _agent_run(db_session, user, *, config: dict) -> tuple[Agent, AgentRun]:
    agent = Agent(
        user_id=user.id,
        name="Research agent",
        kind="research",
        trigger_type="manual",
        config=config,
        autonomy="full",
    )
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=user.id,
        trigger_key=f"manual:{agent.id}:{uuid4().hex}",
        trigger_kind="manual",
        trigger_payload={"objective": "test"},
    )
    db_session.add(run)
    await db_session.flush()
    return agent, run


async def _steps(db_session, run_id) -> list[AgentStep]:
    result = await db_session.execute(
        select(AgentStep)
        .where(AgentStep.run_id == run_id)
        .order_by(AgentStep.idx)
    )
    return list(result.scalars().all())


async def test_runtime_executes_note_and_creates_agent_artifact(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={
            "steps": [
                {"tool": "note", "args": {"text": "Looked through the source."}},
                {
                    "tool": "create_artifact",
                    "args": {
                        "title": "Agent research",
                        "body": "Findings from the run.",
                        "kind": "research",
                    },
                },
            ]
        },
    )

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "done"
    assert run.result["status"] == "done"
    assert run.finished_at is not None
    assert [s.kind for s in await _steps(db_session, run.id)] == [
        "plan",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "verify",
        "final",
    ]
    item = (
        await db_session.execute(select(Item).where(Item.user_id == user.id))
    ).scalar_one()
    assert item.source == "agent"
    assert item.kind == "research"
    assert item.title == "Agent research"
    assert item.metadata_["agent_run_id"] == str(run.id)


async def test_runtime_success_clears_prior_deferred_error(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "Recovered after slot pressure."}}]},
    )
    run.status = "pending"
    run.error = "Too many concurrent agent runs"
    await db_session.flush()

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "done"
    assert run.error is None


async def test_runtime_defers_mutating_action_and_resumes_after_execution(
    db_session, user
):
    _, run = await _agent_run(
        db_session,
        user,
        config={
            "steps": [
                {
                    "tool": "propose_action",
                    "args": {
                        "kind": "send",
                        "tool_name": "send_message_telegram",
                        "action_args": {"text": "running late"},
                        "preview": "Send to you: running late",
                        "recipient_display": "you",
                    },
                },
                {"tool": "note", "args": {"text": "Action was handled."}},
            ]
        },
    )

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "awaiting_approval"
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.agent_run_id == run.id
            )
        )
    ).scalar_one()
    assert row.status == "pending"
    assert row.agent_step_idx == 1

    row.status = "executed"
    row.receipt = {"message_id": 42}
    await db_session.flush()

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "done"
    assert [s.kind for s in await _steps(db_session, run.id)] == [
        "plan",
        "tool_call",
        "approval_request",
        "approval_result",
        "tool_result",
        "tool_call",
        "tool_result",
        "verify",
        "final",
    ]


async def test_runtime_cancel_request_terminates_with_journal_entry(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "x"}}]},
    )
    await cancel_run(db_session, run, reason="user requested")

    await run_job(
        db_session,
        run.id,
        planner=lambda _agent, _run: AgentPlan(plan={"steps": []}, done_spec={}),
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "cancelled"
    steps = await _steps(db_session, run.id)
    assert [s.kind for s in steps] == ["cancel"]
    assert steps[0].payload["reason"] == "user requested"


async def test_runtime_fails_when_verifier_rejects_done_spec(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "x"}}]},
    )

    async def verifier(_session, _agent, _run):
        return {"ok": False, "reason": "missing proof"}

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
        verifier=verifier,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == "Agent verification failed"
    assert [s.kind for s in await _steps(db_session, run.id)] == [
        "plan",
        "tool_call",
        "tool_result",
        "verify",
        "error",
    ]


async def test_runtime_journals_unexpected_executor_error(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "x"}}]},
    )

    async def crashing_executor(*_args, **_kwargs):
        raise RuntimeError("boom")

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=crashing_executor,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == "Unexpected agent runtime error: RuntimeError"
    steps = await _steps(db_session, run.id)
    assert steps[-1].kind == "error"
    assert steps[-1].payload == {"code": "unexpected_error", "message": "RuntimeError"}


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "Agent config must include a steps array before it can run"),
        (
            {"steps": [], "done_spec": ["bad"]},
            "Agent done_spec must be an object",
        ),
    ],
)
async def test_runtime_surfaces_invalid_static_agent_config(
    db_session,
    user,
    config,
    message,
):
    _, run = await _agent_run(db_session, user, config=config)

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == message


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        ({"steps": "bad"}, "plan.steps must be an array"),
        ({"steps": [None]}, "plan.steps[0] must be an object"),
        ({"steps": [{"args": {}}]}, "plan.steps[0].tool must be a non-empty string"),
        (
            {"steps": [{"tool": "note", "args": ["bad"]}]},
            "plan.steps[0].args must be an object",
        ),
    ],
)
async def test_runtime_surfaces_invalid_plans(db_session, user, plan, message):
    _, run = await _agent_run(db_session, user, config={"steps": []})

    async def planner(_agent, _run):
        return AgentPlan(plan=plan, done_spec={})

    await run_job(
        db_session,
        run.id,
        planner=planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == message


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"tool": "note", "args": {}}, "note.text is required"),
        (
            {"tool": "create_artifact", "args": {"body": "body"}},
            "create_artifact.title is required",
        ),
        (
            {"tool": "create_artifact", "args": {"title": "Title"}},
            "create_artifact.body is required",
        ),
        (
            {
                "tool": "create_artifact",
                "args": {"title": "Title", "body": "Body", "kind": " "},
            },
            "create_artifact.kind is required",
        ),
        ({"tool": "search_wai", "args": {}}, "search_wai.query is required"),
        (
            {"tool": "propose_memory", "args": {}},
            "propose_memory.content is required",
        ),
        (
            {
                "tool": "propose_action",
                "args": {"action_args": {}, "preview": "Preview"},
            },
            "propose_action.tool_name is required",
        ),
        (
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "send_message_telegram",
                    "action_args": ["bad"],
                    "preview": "Preview",
                },
            },
            "propose_action.action_args must be an object",
        ),
        (
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "send_message_telegram",
                    "action_args": {},
                },
            },
            "propose_action.preview is required",
        ),
        (
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "desktop_open",
                    "action_args": {"target": "https://wai.computer"},
                    "preview": "Open WaiComputer",
                },
            },
            "propose_action.device_target is required for desktop actions",
        ),
        ({"tool": "unknown", "args": {}}, "Unknown agent tool: unknown"),
    ],
)
async def test_runtime_surfaces_invalid_tool_calls(db_session, user, step, message):
    _, run = await _agent_run(db_session, user, config={"steps": [step]})

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == message


async def test_runtime_executes_search_and_memory_tools(
    db_session,
    user,
    monkeypatch,
):
    async def fake_search(_session, user_id, query, *, limit):
        assert user_id == user.id
        assert query == "agent memory"
        assert limit == 2
        return [
            SimpleNamespace(
                source_kind="item",
                parent_id=str(uuid4()),
                chunk_id=str(uuid4()),
                title="Research",
                kind="note",
                snippet="agent memory snippet",
                score=0.91,
                created_at="2026-06-04T00:00:00Z",
            )
        ]

    outcomes = [
        SimpleNamespace(
            proposal=SimpleNamespace(id=uuid4(), status="pending"),
            decision="created",
        ),
        None,
    ]

    async def fake_propose_block_update(
        _session,
        user_id,
        *,
        block_label,
        operation,
        content,
        target_line,
        confidence,
        authority,
        summary,
        evidence,
    ):
        assert user_id == user.id
        assert block_label == "topics"
        assert operation == "append"
        assert content == "Remember this finding"
        assert target_line is None
        assert confidence == 0.6
        assert authority == "agent"
        assert summary is None
        assert evidence is None
        return outcomes.pop(0)

    monkeypatch.setattr("app.core.agent_runtime.unified_search", fake_search)
    monkeypatch.setattr(
        "app.core.agent_runtime.propose_block_update",
        fake_propose_block_update,
    )
    _, run = await _agent_run(
        db_session,
        user,
        config={
            "steps": [
                {"tool": "search_wai", "args": {"query": "agent memory", "limit": 2}},
                {
                    "tool": "propose_memory",
                    "args": {"content": "Remember this finding"},
                },
                {
                    "tool": "propose_memory",
                    "args": {"content": "Remember this finding"},
                },
            ]
        },
    )

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "done"
    tool_results = [
        step.payload
        for step in await _steps(db_session, run.id)
        if step.kind == "tool_result"
    ]
    assert tool_results[0]["hits"][0]["snippet"] == "agent memory snippet"
    assert tool_results[1]["decision"] == "created"
    assert tool_results[2] == {"proposal": "duplicate"}


async def test_create_artifact_and_propose_action_are_idempotent(db_session, user):
    agent, run = await _agent_run(db_session, user, config={"steps": []})
    artifact_step = {
        "tool": "create_artifact",
        "args": {"title": "Artifact", "body": "Body", "kind": "note"},
    }

    first = await execute_agent_step(
        db_session,
        agent,
        run,
        artifact_step,
        7,
        "artifact-key",
    )
    second = await execute_agent_step(
        db_session,
        agent,
        run,
        artifact_step,
        7,
        "artifact-key",
    )

    assert first.payload["created"] is True
    assert second.payload == {"item_id": first.payload["item_id"], "created": False}

    action_step = {
        "tool": "propose_action",
        "args": {
            "kind": "send",
            "tool_name": "send_message_telegram",
            "action_args": {"text": "hello"},
            "preview": "Send hello",
        },
    }
    first_action = await execute_agent_step(
        db_session,
        agent,
        run,
        action_step,
        8,
        "action-key",
    )
    second_action = await execute_agent_step(
        db_session,
        agent,
        run,
        action_step,
        8,
        "action-key",
    )

    assert first_action.status == "awaiting_approval"
    assert second_action.status == "awaiting_approval"
    assert second_action.payload == {
        "action_id": first_action.payload["action_id"],
        "status": "pending",
    }


async def test_runtime_fails_when_approval_row_is_missing(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
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
    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.agent_run_id == run.id
            )
        )
    ).scalar_one()
    await db_session.delete(row)
    run.status = "running"
    await db_session.flush()

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == "Approval row missing"


async def test_runtime_fails_when_approval_is_not_executed(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
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
    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.agent_run_id == run.id
            )
        )
    ).scalar_one()
    row.status = "rejected"
    run.status = "running"
    await db_session.flush()

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == "Approval rejected"
    assert (await _steps(db_session, run.id))[-1].payload == {
        "code": "approval_not_executed",
        "status": "rejected",
    }


async def test_runtime_honors_cancel_requested_flag(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "later"}}]},
    )
    run.cancel_requested_at = datetime.now(timezone.utc)
    await db_session.flush()

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=execute_agent_step,
    )
    await db_session.refresh(run)

    assert run.status == "cancelled"
    assert [step.kind for step in await _steps(db_session, run.id)] == ["cancel"]


async def test_cancel_run_is_noop_for_terminal_runs(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "x"}}]},
    )
    run.status = "done"
    await db_session.flush()

    result = await cancel_run(db_session, run, reason="too late")

    assert result is run
    assert run.status == "done"
    assert await _steps(db_session, run.id) == []


async def test_runtime_surfaces_unknown_executor_status(db_session, user):
    _, run = await _agent_run(
        db_session,
        user,
        config={"steps": [{"tool": "note", "args": {"text": "x"}}]},
    )

    async def strange_executor(*_args, **_kwargs):
        return AgentStepResult(status="paused", payload={})

    await run_job(
        db_session,
        run.id,
        planner=static_config_planner,
        executor=strange_executor,
    )
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error == "Executor returned unknown status paused"


async def test_run_job_surfaces_missing_run_with_executor(db_session):
    with pytest.raises(AgentRuntimeError) as exc:
        await run_job(
            db_session,
            uuid4(),
            planner=static_config_planner,
            executor=execute_agent_step,
        )

    assert exc.value.code == "run_not_found"
