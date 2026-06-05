"""Built-in Wai agent session routes."""

from uuid import UUID

from sqlalchemy import select

from app.models.agent import AgentRun, AgentStep
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
