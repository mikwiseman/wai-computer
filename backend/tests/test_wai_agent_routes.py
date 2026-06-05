"""Built-in Wai agent session routes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

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
