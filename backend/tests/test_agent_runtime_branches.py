"""Branch coverage for the journalled agent harness (``app.core.agent_runtime``).

Complements test_agent_runtime.py / test_agent_runtime_execution.py with the
context tools (``load_context`` / ``respond_from_context`` / ``respond_from_search``),
per-tool argument validation that the static-config planner would otherwise
shadow, delegate-target resolution edges, and replay/ownership guards.
All LLM-ish collaborators (ask_brain, unified_search) are faked — zero network.
"""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.agent_capabilities import MAX_AGENT_STEPS
from app.core.agent_runtime import (
    AgentPlan,
    AgentRuntimeError,
    _load_agent,
    _load_delegate_target,
    execute_agent_step,
    run_job,
    static_config_planner,
)
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.brain_map import BrainMap, BrainMapRevision
from app.models.companion_pending_action import CompanionPendingAction
from app.models.item import Item, ItemSummary
from app.models.recording import ActionItem, Recording, Segment, Summary
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def user(db_session) -> User:
    u = User(email=f"agent-branch-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(u)
    await db_session.flush()
    return u


async def _agent_run(db_session, user, *, config: dict | None = None, **run_kwargs):
    agent = Agent(
        user_id=user.id,
        name="Branch agent",
        kind="research",
        trigger_type="manual",
        config=config or {"steps": []},
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
        **run_kwargs,
    )
    db_session.add(run)
    await db_session.flush()
    return agent, run


async def _steps(db_session, run_id) -> list[AgentStep]:
    result = await db_session.execute(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.idx)
    )
    return list(result.scalars().all())


async def _recording_with_details(db_session, user) -> Recording:
    recording = Recording(
        user_id=user.id, title="Roadmap review", type="meeting", status="ready"
    )
    db_session.add(recording)
    await db_session.flush()
    db_session.add(
        Summary(
            recording_id=recording.id,
            summary="Hiring is the biggest roadmap risk.",
            topics=["roadmap"],
            decisions=["open the role"],
        )
    )
    db_session.add(
        Segment(recording_id=recording.id, content="We reviewed the roadmap.", start_ms=0)
    )
    db_session.add(
        Segment(
            recording_id=recording.id,
            content="Risk detail " + "very long transcript " * 120,
            start_ms=1000,
        )
    )
    db_session.add(
        ActionItem(
            recording_id=recording.id,
            task="Open the role",
            owner="Mik",
            due_date=date(2026, 6, 12),
            priority="high",
            status="pending",
        )
    )
    db_session.add(ActionItem(recording_id=recording.id, task="Draft the JD"))
    await db_session.flush()
    return recording


# ---------------------------------------------------------------------------
# run_job guards and replay edges
# ---------------------------------------------------------------------------


async def test_load_agent_surfaces_missing_agent(db_session):
    with pytest.raises(AgentRuntimeError) as exc:
        await _load_agent(db_session, uuid4())
    assert exc.value.code == "agent_not_found"


async def test_run_job_surfaces_run_user_mismatch(db_session, user):
    other = User(email=f"other-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(other)
    await db_session.flush()
    agent, run = await _agent_run(db_session, user)
    run.user_id = other.id
    await db_session.flush()

    with pytest.raises(AgentRuntimeError) as exc:
        await run_job(
            db_session, run.id, planner=static_config_planner, executor=execute_agent_step
        )

    assert exc.value.code == "agent_run_user_mismatch"


async def test_run_job_completes_plan_without_steps_and_promotes_content_hash(
    db_session, user
):
    agent, run = await _agent_run(db_session, user, content_hash="sha-new")
    assert agent.content_hash is None

    async def planner(_agent, _run):
        return AgentPlan(plan={"note": "no steps key"}, done_spec={})

    await run_job(db_session, run.id, planner=planner, executor=execute_agent_step)
    await db_session.refresh(run)

    assert run.status == "done"
    assert agent.content_hash == "sha-new"
    assert agent.last_run_at == run.finished_at


async def test_run_job_rejects_planner_plan_exceeding_max_steps(db_session, user):
    _, run = await _agent_run(db_session, user)

    async def planner(_agent, _run):
        steps = [{"tool": "note", "args": {"text": "x"}}] * (MAX_AGENT_STEPS + 1)
        return AgentPlan(plan={"steps": steps}, done_spec={})

    await run_job(db_session, run.id, planner=planner, executor=execute_agent_step)
    await db_session.refresh(run)

    assert run.status == "failed"
    assert f"plan.steps cannot exceed {MAX_AGENT_STEPS} steps" in run.error


async def test_resume_replays_step_that_already_has_tool_result(db_session, user):
    """A resume must skip a completed earlier step via its journalled
    tool_result instead of re-executing it."""
    _, run = await _agent_run(
        db_session,
        user,
        config={
            "steps": [
                {"tool": "note", "args": {"text": "done before the pause"}},
                {
                    "tool": "propose_action",
                    "args": {
                        "kind": "send",
                        "tool_name": "send_message_telegram",
                        "action_args": {"text": "hello"},
                        "preview": "Send hello",
                    },
                },
            ]
        },
    )

    await run_job(
        db_session, run.id, planner=static_config_planner, executor=execute_agent_step
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
    row.status = "executed"
    row.receipt = {"message_id": 7}
    await db_session.flush()

    await run_job(
        db_session, run.id, planner=static_config_planner, executor=execute_agent_step
    )
    await db_session.refresh(run)

    assert run.status == "done"
    note_results = [
        step
        for step in await _steps(db_session, run.id)
        if step.kind == "tool_result" and step.payload.get("text") == "done before the pause"
    ]
    assert len(note_results) == 1  # replayed, never duplicated


# ---------------------------------------------------------------------------
# load_context: recordings and items
# ---------------------------------------------------------------------------


async def test_load_context_returns_recording_payload(db_session, user):
    recording = await _recording_with_details(db_session, user)
    agent, run = await _agent_run(db_session, user)

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {
            "tool": "load_context",
            "args": {"ref_type": "recording", "ref_id": str(recording.id)},
        },
        0,
        "ctx-recording",
    )

    assert result.status == "done"
    payload = result.payload
    assert payload["ref_type"] == "recording"
    assert payload["ref_id"] == str(recording.id)
    assert payload["title"] == "Roadmap review"
    assert payload["summary"] == "Hiring is the biggest roadmap risk."
    assert payload["topics"] == ["roadmap"]
    assert payload["decisions"] == ["open the role"]
    # Both rows share created_at within one flush, so sort by task for a
    # deterministic assertion (the journal orders by created_at, id).
    by_task = {action["task"]: action for action in payload["action_items"]}
    assert by_task["Open the role"] == {
        "task": "Open the role",
        "owner": "Mik",
        "due_date": "2026-06-12",
        "priority": "high",
        "status": "pending",
    }
    assert by_task["Draft the JD"]["due_date"] is None
    assert payload["transcript_excerpt"].startswith("We reviewed the roadmap.")
    assert payload["transcript_excerpt"].endswith("...")  # shortened to 1600 chars
    assert len(payload["transcript_excerpt"]) <= 1600


async def test_load_context_returns_item_payload(db_session, user):
    item = Item(
        user_id=user.id,
        source="upload",
        kind="article",
        title="Pricing notes",
        body="The pricing page must lead with annual plans.",
        content_hash=uuid4().hex,
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        ItemSummary(
            item_id=item.id,
            summary="Lead with annual pricing.",
            key_points=["annual first"],
            action_items=["update pricing page"],
        )
    )
    await db_session.flush()
    agent, run = await _agent_run(db_session, user)

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {"tool": "load_context", "args": {"ref_type": "item", "ref_id": str(item.id)}},
        0,
        "ctx-item",
    )

    assert result.payload == {
        "ref_type": "item",
        "ref_id": str(item.id),
        "title": "Pricing notes",
        "kind": "article",
        "summary": "Lead with annual pricing.",
        "key_points": ["annual first"],
        "action_items": ["update pricing page"],
        "body_excerpt": "The pricing page must lead with annual plans.",
    }


@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        (
            {"ref_type": "recording", "ref_id": "not-a-uuid"},
            "invalid_tool_args",
            "load_context.ref_id must be a UUID string",
        ),
        (
            {"ref_type": "calendar", "ref_id": str(uuid4())},
            "invalid_tool_args",
            "load_context.ref_type must be recording or item",
        ),
        (
            {"ref_type": "recording", "ref_id": str(uuid4())},
            "context_not_found",
            "Recording context not found",
        ),
        (
            {"ref_type": "item", "ref_id": str(uuid4())},
            "context_not_found",
            "Material context not found",
        ),
    ],
)
async def test_load_context_surfaces_invalid_refs(db_session, user, args, code, message):
    agent, run = await _agent_run(db_session, user)

    with pytest.raises(AgentRuntimeError) as exc:
        await execute_agent_step(
            db_session, agent, run, {"tool": "load_context", "args": args}, 0, "ctx-bad"
        )

    assert exc.value.code == code
    assert message in exc.value.message


# ---------------------------------------------------------------------------
# respond_from_context / respond_from_search
# ---------------------------------------------------------------------------


async def test_respond_from_context_continues_from_recording_summary(db_session, user):
    recording = await _recording_with_details(db_session, user)
    agent, run = await _agent_run(db_session, user)

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {
            "tool": "respond_from_context",
            "args": {
                "ref_type": "recording",
                "ref_id": str(recording.id),
                "objective": "continue the roadmap review",
            },
        },
        0,
        "respond-ctx",
    )

    assert result.status == "done"
    assert result.payload["text"].startswith("Continuing from Roadmap review:")
    assert "Hiring is the biggest roadmap risk." in result.payload["text"]
    assert result.payload["context"]["ref_type"] == "recording"


async def test_respond_from_context_reports_unreadable_source(db_session, user):
    recording = Recording(
        user_id=user.id, title="Silent capture", type="note", status="processing"
    )
    db_session.add(recording)
    await db_session.flush()
    agent, run = await _agent_run(db_session, user)

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {
            "tool": "respond_from_context",
            "args": {"ref_type": "recording", "ref_id": str(recording.id)},
        },
        0,
        "respond-ctx-empty",
    )

    assert (
        result.payload["text"]
        == "I found Silent capture, but it has no readable summary or transcript yet."
    )


async def test_respond_from_search_reports_no_hits(db_session, user):
    """A run whose only earlier tool_result has no hits list responds with the
    not-found text (the latest-search scan skips non-search payloads)."""
    _, run = await _agent_run(
        db_session,
        user,
        config={
            "steps": [
                {"tool": "note", "args": {"text": "no search happened"}},
                {"tool": "respond_from_search", "args": {"query": "quarterly OKRs"}},
            ]
        },
    )

    await run_job(
        db_session, run.id, planner=static_config_planner, executor=execute_agent_step
    )
    await db_session.refresh(run)

    assert run.status == "done"
    assert (
        run.result["output_text"]
        == "I could not find relevant Wai material for: quarterly OKRs"
    )


async def test_respond_from_search_summarizes_latest_hits(db_session, user, monkeypatch):
    async def fake_search(_session, _user_id, query, *, limit):
        assert query == "pricing"
        return [
            SimpleNamespace(
                source_kind="item",
                parent_id=str(uuid4()),
                chunk_id=str(uuid4()),
                title="Pricing notes",
                kind="article",
                snippet="Annual plans first.",
                score=0.9,
                created_at="2026-06-01T00:00:00Z",
            ),
            SimpleNamespace(
                source_kind="item",
                parent_id=str(uuid4()),
                chunk_id=str(uuid4()),
                title=None,
                kind="note",
                snippet="",
                score=0.5,
                created_at="2026-06-02T00:00:00Z",
            ),
        ]

    monkeypatch.setattr("app.core.agent_runtime.unified_search", fake_search)
    _, run = await _agent_run(
        db_session,
        user,
        config={
            "steps": [
                {"tool": "search_wai", "args": {"query": "pricing", "limit": 5}},
                {"tool": "respond_from_search", "args": {"query": "pricing"}},
            ]
        },
    )

    await run_job(
        db_session, run.id, planner=static_config_planner, executor=execute_agent_step
    )
    await db_session.refresh(run)

    assert run.status == "done"
    lines = run.result["output_text"].split("\n")
    assert lines[0] == "Found 2 relevant Wai result(s) for: pricing"
    assert lines[1] == "- Pricing notes: Annual plans first."
    assert lines[2] == "- note"  # falls back to kind, no snippet line


# ---------------------------------------------------------------------------
# ask_brain edges
# ---------------------------------------------------------------------------


async def test_ask_brain_passes_through_string_freshness(db_session, user, monkeypatch):
    async def fake_ask_brain(_session, _user_id, _question):
        return SimpleNamespace(
            answer="The answer [1]",
            citations=[],
            gaps=[],
            freshness=SimpleNamespace(
                newest_source_at="2026-06-01",  # no .isoformat() — stringified as-is
                weeks_since=1,
                stale=True,
            ),
        )

    monkeypatch.setattr("app.core.agent_runtime.ask_brain", fake_ask_brain)
    agent, run = await _agent_run(db_session, user)

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {"tool": "ask_brain", "args": {"question": "What changed?"}},
        0,
        "ask-brain-freshness",
    )

    assert result.payload["freshness"] == {
        "newest_source_at": "2026-06-01",
        "weeks_since": 1,
        "stale": True,
    }


async def test_ask_brain_surfaces_fully_empty_answer(db_session, user, monkeypatch):
    async def fake_ask_brain(_session, _user_id, _question):
        return SimpleNamespace(
            answer="",
            citations=[],
            gaps=[],
            freshness=SimpleNamespace(newest_source_at=None, weeks_since=None, stale=False),
        )

    monkeypatch.setattr("app.core.agent_runtime.ask_brain", fake_ask_brain)
    agent, run = await _agent_run(db_session, user)

    with pytest.raises(AgentRuntimeError) as exc:
        await execute_agent_step(
            db_session,
            agent,
            run,
            {"tool": "ask_brain", "args": {"question": "Anything?"}},
            0,
            "ask-brain-empty",
        )

    assert exc.value.code == "empty_brain_answer"


# ---------------------------------------------------------------------------
# create_brain_map replay
# ---------------------------------------------------------------------------


async def test_create_brain_map_replays_existing_agent_map(db_session, user):
    agent, run = await _agent_run(db_session, user)
    source_ref = f"agent_run:{run.id}:step:5"
    brain_map = BrainMap(
        user_id=user.id,
        title="Roadmap map",
        prompt="Map the roadmap",
        map_type="topics",
        origin="agent",
        status="draft",
        source_scope={"agent_source_ref": source_ref},
        layout={},
    )
    db_session.add(brain_map)
    await db_session.flush()
    revision = BrainMapRevision(
        map_id=brain_map.id,
        user_id=user.id,
        revision_index=1,
        projection={"nodes": []},
        source_fingerprint="f" * 64,
        source_count=0,
        freshness={},
        diff={},
        citations=[],
        compiled_at=run.created_at,
    )
    db_session.add(revision)
    await db_session.flush()
    brain_map.current_revision_id = revision.id
    await db_session.flush()

    result = await execute_agent_step(
        db_session,
        agent,
        run,
        {"tool": "create_brain_map", "args": {"prompt": "Map the roadmap"}},
        5,
        "brain-map-replay",
    )

    assert result.payload == {
        "map_id": str(brain_map.id),
        "revision_id": str(revision.id),
        "status": "draft",
        "title": "Roadmap map",
        "created": False,
    }


# ---------------------------------------------------------------------------
# delegate_agent target resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            {"agent_id": "not-a-uuid", "objective": "Review"},
            "delegate_agent.agent_id must be a UUID string",
        ),
        (
            {"agent_id": str(uuid4()), "objective": "Review"},
            "delegate_agent target agent not found",
        ),
        ({"objective": "Review"}, "exactly one of agent_id or agent_name"),
        (
            {"agent_id": str(uuid4()), "agent_name": "Reviewer", "objective": "Review"},
            "exactly one of agent_id or agent_name",
        ),
        ({"agent_name": "Reviewer"}, "delegate_agent.objective is required"),
    ],
)
async def test_delegate_agent_argument_validation(db_session, user, args, message):
    agent, run = await _agent_run(db_session, user)

    with pytest.raises(AgentRuntimeError) as exc:
        await execute_agent_step(
            db_session, agent, run, {"tool": "delegate_agent", "args": args}, 0, "dl-bad"
        )

    assert exc.value.code == "invalid_tool_args"
    assert message in exc.value.message


async def test_delegate_agent_rejects_ambiguous_target_name(db_session, user):
    agent, run = await _agent_run(db_session, user)
    for _ in range(2):
        db_session.add(
            Agent(user_id=user.id, name="Twin", kind="review", trigger_type="manual")
        )
    await db_session.flush()

    with pytest.raises(AgentRuntimeError) as exc:
        await execute_agent_step(
            db_session,
            agent,
            run,
            {"tool": "delegate_agent", "args": {"agent_name": "Twin", "objective": "Go"}},
            0,
            "dl-ambiguous",
        )

    assert "delegate_agent target agent name is ambiguous" in exc.value.message


async def test_delegate_agent_rejects_disabled_target(db_session, user):
    agent, run = await _agent_run(db_session, user)
    db_session.add(
        Agent(
            user_id=user.id,
            name="Sleeper",
            kind="review",
            trigger_type="manual",
            enabled=False,
        )
    )
    await db_session.flush()

    with pytest.raises(AgentRuntimeError) as exc:
        await execute_agent_step(
            db_session,
            agent,
            run,
            {"tool": "delegate_agent", "args": {"agent_name": "Sleeper", "objective": "Go"}},
            0,
            "dl-disabled",
        )

    assert "delegate_agent target agent is disabled" in exc.value.message


async def test_load_delegate_target_requires_an_identifier(db_session, user):
    _, run = await _agent_run(db_session, user)

    with pytest.raises(AgentRuntimeError) as exc:
        await _load_delegate_target(db_session, run, agent_id=None, agent_name=None)

    assert "exactly one of agent_id or agent_name" in exc.value.message


# ---------------------------------------------------------------------------
# execute_agent_step argument validation the static planner would shadow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "code", "message"),
    [
        ({"tool": "note", "args": {}}, "invalid_tool_args", "note.text is required"),
        (
            {"tool": "create_artifact", "args": {"body": "Body"}},
            "invalid_tool_args",
            "create_artifact.title is required",
        ),
        (
            {"tool": "create_artifact", "args": {"title": "Title"}},
            "invalid_tool_args",
            "create_artifact.body is required",
        ),
        (
            {"tool": "create_brain_map", "args": {}},
            "invalid_tool_args",
            "create_brain_map.prompt is required",
        ),
        (
            {"tool": "create_brain_map", "args": {"prompt": "x", "source_scope": ["bad"]}},
            "invalid_tool_args",
            "create_brain_map.source_scope must be an object",
        ),
        ({"tool": "ask_brain", "args": {}}, "invalid_tool_args", "ask_brain.question is required"),
        (
            {"tool": "ask_brain", "args": {"question": "x", "limit": 0}},
            "invalid_tool_args",
            "ask_brain.limit must be 1..",
        ),
        ({"tool": "search_wai", "args": {}}, "invalid_tool_args", "search_wai.query is required"),
        (
            {"tool": "search_wai", "args": {"query": "x", "limit": True}},
            "invalid_tool_args",
            "search_wai.limit must be 1..",
        ),
        (
            {"tool": "respond", "args": {"text": "  "}},
            "invalid_tool_args",
            "respond.text is required",
        ),
        (
            {"tool": "missing_capability", "args": {"reason": "no tool"}},
            "invalid_tool_args",
            "missing_capability.capability is required",
        ),
        (
            {"tool": "missing_capability", "args": {"capability": "calendar"}},
            "invalid_tool_args",
            "missing_capability.reason is required",
        ),
        (
            {"tool": "propose_memory", "args": {}},
            "invalid_tool_args",
            "propose_memory.content is required",
        ),
        (
            {"tool": "propose_action", "args": {"preview": "p"}},
            "invalid_tool_args",
            "propose_action.tool_name is required",
        ),
        (
            {"tool": "propose_action", "args": {"tool_name": "rm_rf", "preview": "p"}},
            "invalid_tool_args",
            "Unsupported action tool: rm_rf",
        ),
        (
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "send_message_telegram",
                    "action_args": ["bad"],
                    "preview": "p",
                },
            },
            "invalid_tool_args",
            "propose_action.action_args must be an object",
        ),
        (
            {
                "tool": "propose_action",
                "args": {"tool_name": "send_message_telegram", "action_args": {}},
            },
            "invalid_tool_args",
            "propose_action.preview is required",
        ),
        (
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "desktop_open",
                    "action_args": {"target": "https://wai.computer"},
                    "preview": "Open",
                },
            },
            "invalid_tool_args",
            "propose_action.device_target is required for desktop actions",
        ),
        (
            {
                "tool": "propose_action",
                "args": {
                    "tool_name": "send_message_telegram",
                    "action_args": {"text": "hi"},
                    "preview": "Send hi",
                    "ttl_seconds": 0,
                },
            },
            "invalid_tool_args",
            "propose_action.ttl_seconds must be 1..",
        ),
        ({"tool": "teleport", "args": {}}, "unknown_agent_tool", "Unknown agent tool: teleport"),
    ],
)
async def test_execute_agent_step_validates_tool_args(db_session, user, step, code, message):
    agent, run = await _agent_run(db_session, user)

    with pytest.raises(AgentRuntimeError) as exc:
        await execute_agent_step(db_session, agent, run, step, 0, f"args-{uuid4().hex}")

    assert exc.value.code == code
    assert message in exc.value.message
