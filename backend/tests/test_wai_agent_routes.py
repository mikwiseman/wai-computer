"""Built-in Wai agent session routes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.routes import wai as wai_routes
from app.core.agent_dispatch import AgentDispatchError
from app.models.agent import AgentRun, AgentStep
from app.models.brain_map import BrainMap
from app.models.item import Item


async def test_wai_task_inline_creates_session_run_and_html_artifact(
    client, auth_headers, db_session
):
    response = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Build a web page of AI hackathon",
            "run_inline": True,
            "idempotency_key": "hackathon-page",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["session"]["title"] == "Build a web page of AI hackathon"
    assert body["run"]["conversation_id"] == body["session"]["id"]
    assert body["run"]["status"] == "done"
    assert body["run"]["result"]["output_text"].startswith("Created an HTML artifact")
    artifact = body["run"]["result"]["artifacts"][0]
    assert artifact["filename"] == "index.html"
    assert artifact["mime_type"] == "text/html"
    assert artifact["preview_kind"] == "html"

    run = (
        await db_session.execute(
            select(AgentRun).where(AgentRun.id == UUID(body["run"]["id"]))
        )
    ).scalar_one()
    steps = list(
        (
            await db_session.execute(
                select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.idx)
            )
        )
        .scalars()
        .all()
    )
    assert [step.kind for step in steps] == [
        "plan",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "verify",
        "final",
    ]
    item = (
        await db_session.execute(select(Item).where(Item.id == UUID(artifact["item_id"])))
    ).scalar_one()
    assert item.kind == "html"
    assert item.metadata_["agent_run_id"] == str(run.id)


async def test_wai_task_inline_surfaces_missing_shell_capability(client, auth_headers):
    response = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Run shell command ls",
            "run_inline": True,
            "idempotency_key": "shell-blocked",
        },
    )

    assert response.status_code == 201, response.text
    run = response.json()["run"]
    assert run["status"] == "failed"
    assert "local.shell" in run["error"]


async def test_wai_task_inline_answers_normal_questions_from_brain(
    client,
    auth_headers,
    db_session,
    monkeypatch,
):
    calls: list[tuple[str, int | None]] = []

    async def fake_ask_brain(_session, _user_id, question, *, limit=None):
        calls.append((question, limit))
        return SimpleNamespace(
            answer="The roadmap risk is hiring [1]",
            citations=[
                SimpleNamespace(
                    id="segment-1",
                    source_kind="recording",
                    source_id="11111111-1111-4111-8111-111111111111",
                    title="Roadmap review",
                    start_ms=42000,
                )
            ],
            gaps=[],
            freshness=SimpleNamespace(
                newest_source_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                weeks_since=0,
                stale=False,
            ),
        )

    monkeypatch.setattr("app.core.agent_runtime.ask_brain", fake_ask_brain)
    response = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "What is the roadmap risk?",
            "run_inline": True,
            "idempotency_key": "roadmap-risk-brain",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["run"]["status"] == "done"
    assert body["run"]["result"]["output_text"] == "The roadmap risk is hiring [1]"
    assert body["run"]["result"]["citations"][0]["title"] == "Roadmap review"
    assert calls == [("What is the roadmap risk?", 12)]

    run_id = UUID(body["run"]["id"])
    steps = list(
        (
            await db_session.execute(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.idx)
            )
        )
        .scalars()
        .all()
    )
    planned_steps = steps[0].payload["plan"]["steps"]
    assert planned_steps[1] == {
        "tool": "ask_brain",
        "args": {"question": "What is the roadmap risk?", "limit": 12},
    }
    assert all(step["tool"] != "search_wai" for step in planned_steps)


async def test_wai_task_inline_creates_brain_map_for_map_requests(
    client,
    auth_headers,
    db_session,
    monkeypatch,
):
    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.brain_maps.unified_search", fake_search)

    response = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Create a schema map of roadmap risks",
            "run_inline": True,
            "idempotency_key": "roadmap-risk-map",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["run"]["status"] == "done"
    brain_map_ref = body["run"]["result"]["brain_maps"][0]
    assert brain_map_ref["map_id"]
    assert brain_map_ref["status"] == "draft"
    assert body["run"]["result"]["output_text"].startswith("Created a draft Brain Map")

    stored = (
        await db_session.execute(
            select(BrainMap).where(BrainMap.id == UUID(brain_map_ref["map_id"]))
        )
    ).scalar_one()
    assert stored.origin == "agent"
    assert stored.title == "Create a schema map of roadmap risks"

    run_id = UUID(body["run"]["id"])
    steps = list(
        (
            await db_session.execute(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.idx)
            )
        )
        .scalars()
        .all()
    )
    planned_steps = steps[0].payload["plan"]["steps"]
    assert planned_steps[1]["tool"] == "create_brain_map"
    assert planned_steps[2]["tool"] == "respond"


async def test_wai_task_inline_carries_chat_context_to_brain_map(
    client,
    auth_headers,
    db_session,
    monkeypatch,
):
    async def fake_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.brain_maps.unified_search", fake_search)
    chat_id = "11111111-1111-4111-8111-111111111111"

    response = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Create a map of this Wai thread",
            "context": {"ref_type": "chat", "ref_id": chat_id},
            "run_inline": True,
            "idempotency_key": "chat-context-map",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    brain_map_ref = body["run"]["result"]["brain_maps"][0]
    stored = (
        await db_session.execute(
            select(BrainMap).where(BrainMap.id == UUID(brain_map_ref["map_id"]))
        )
    ).scalar_one()
    assert stored.origin == "agent"
    assert stored.source_scope["sources"] == [
        {"source_kind": "chat", "source_id": chat_id}
    ]

    run_id = UUID(body["run"]["id"])
    steps = list(
        (
            await db_session.execute(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.idx)
            )
        )
        .scalars()
        .all()
    )
    planned_steps = steps[0].payload["plan"]["steps"]
    assert planned_steps[1]["args"]["source_scope"] == {
        "sources": [{"source_kind": "chat", "source_id": chat_id}]
    }


async def test_create_wai_session_returns_persisted_session(client, auth_headers):
    context = {"ref_type": "chat", "ref_id": "11111111-1111-4111-8111-111111111111"}
    response = await client.post(
        "/api/wai/sessions",
        headers=auth_headers,
        json={"title": "Roadmap planning", "context": context},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["title"] == "Roadmap planning"
    assert body["scope"]["kind"] == "wai_session"
    assert body["scope"]["active_context"] == context
    assert body["last_message_at"] is not None
    assert body["created_at"]
    assert body["updated_at"]


async def test_get_wai_session_detail_includes_latest_run_and_steps(client, auth_headers):
    created = await client.post("/api/wai/sessions", headers=auth_headers, json={})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    task = await client.post(
        f"/api/wai/sessions/{session_id}/tasks",
        headers=auth_headers,
        json={
            "objective": "Build a web page of demo day",
            "run_inline": True,
            "idempotency_key": "demo-day",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["created"] is True
    assert task.json()["session"]["id"] == session_id

    detail = await client.get(f"/api/wai/sessions/{session_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == session_id
    assert body["latest_run"]["id"] == task.json()["run"]["id"]
    assert body["latest_run"]["status"] == "done"
    assert body["latest_run"]["conversation_id"] == session_id
    assert body["steps"]
    assert body["steps"][0]["kind"] == "plan"
    assert body["steps"][0]["idx"] == 0
    assert body["steps"][0]["run_id"] == body["latest_run"]["id"]

    limited = await client.get(
        f"/api/wai/sessions/{session_id}",
        headers=auth_headers,
        params={"steps_limit": 2},
    )
    assert limited.status_code == 200, limited.text
    assert len(limited.json()["steps"]) == 2


async def test_get_wai_session_detail_without_runs_and_missing_session(client, auth_headers):
    created = await client.post(
        "/api/wai/sessions", headers=auth_headers, json={"title": "Empty"}
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    detail = await client.get(f"/api/wai/sessions/{session_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["latest_run"] is None
    assert detail.json()["steps"] == []

    missing = await client.get(f"/api/wai/sessions/{uuid4()}", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Wai session not found"


async def test_wai_session_task_queues_run_and_is_idempotent(client, auth_headers, monkeypatch):
    dispatched: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.wai.enqueue_agent_run",
        lambda run_id: dispatched.append(str(run_id)) or "task-1",
    )
    created = await client.post("/api/wai/sessions", headers=auth_headers, json={})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    started = await client.post(
        f"/api/wai/sessions/{session_id}/tasks",
        headers=auth_headers,
        json={
            "objective": "Summarize my week",
            "idempotency_key": "weekly",
            "run_inline": False,
        },
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["created"] is True
    assert body["run"]["status"] == "pending"
    assert body["session"]["id"] == session_id
    assert dispatched == [body["run"]["id"]]

    redelivered = await client.post(
        f"/api/wai/sessions/{session_id}/tasks",
        headers=auth_headers,
        json={
            "objective": "Summarize my week",
            "idempotency_key": "weekly",
            "run_inline": False,
        },
    )
    assert redelivered.status_code == 201, redelivered.text
    assert redelivered.json()["created"] is False
    assert redelivered.json()["run"]["id"] == body["run"]["id"]
    assert dispatched == [body["run"]["id"]]


async def test_wai_session_task_missing_session_returns_404(client, auth_headers):
    response = await client.post(
        f"/api/wai/sessions/{uuid4()}/tasks",
        headers=auth_headers,
        json={"objective": "anything", "run_inline": True},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Wai session not found"


async def test_wai_task_dispatch_failure_marks_run_failed(
    client, auth_headers, db_session, monkeypatch
):
    def fail_dispatch(_run_id):
        raise AgentDispatchError("Could not start agent run")

    monkeypatch.setattr("app.api.routes.wai.enqueue_agent_run", fail_dispatch)
    response = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Queue me for later",
            "idempotency_key": "broker-down",
            "run_inline": False,
        },
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Could not start agent run"

    run = (await db_session.execute(select(AgentRun))).scalar_one()
    assert run.status == "failed"
    assert run.error == "Could not start agent run"
    assert run.finished_at is not None


async def test_wai_session_events_requires_existing_session_and_run(client, auth_headers):
    created = await client.post("/api/wai/sessions", headers=auth_headers, json={})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    no_run = await client.get(
        f"/api/wai/sessions/{session_id}/events", headers=auth_headers
    )
    assert no_run.status_code == 404
    assert no_run.json()["detail"] == "Wai run not found"

    missing = await client.get(f"/api/wai/sessions/{uuid4()}/events", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Wai session not found"


async def test_wai_session_events_stream_terminal_run(client, auth_headers):
    task = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Build a web page of AI meetup",
            "run_inline": True,
            "idempotency_key": "meetup-page",
        },
    )
    assert task.status_code == 201, task.text
    session_id = task.json()["session"]["id"]
    run_id = task.json()["run"]["id"]

    async with client.stream(
        "GET", f"/api/wai/sessions/{session_id}/events", headers=auth_headers
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = body.decode("utf-8")
    assert "event: step" in text
    assert "event: run" in text
    assert f'"id": "{run_id}"' in text
    assert '"status": "done"' in text


async def test_wai_session_events_polls_until_timeout_for_pending_run(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("app.api.routes.wai.enqueue_agent_run", lambda _run_id: "task-1")
    monkeypatch.setattr("app.api.routes.wai.RUN_EVENTS_POLL_SECONDS", 0.01)
    monkeypatch.setattr("app.api.routes.wai.RUN_EVENTS_MAX_SECONDS", 0.03)

    task = await client.post(
        "/api/wai/tasks",
        headers=auth_headers,
        json={
            "objective": "Queue and wait",
            "idempotency_key": "pending-stream",
            "run_inline": False,
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["run"]["status"] == "pending"
    session_id = task.json()["session"]["id"]

    async with client.stream(
        "GET", f"/api/wai/sessions/{session_id}/events", headers=auth_headers
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    assert body == b""


def test_event_session_maker_requires_database_bind():
    with pytest.raises(RuntimeError, match="cannot resolve database bind"):
        wai_routes._event_session_maker(SimpleNamespace(bind=None))
