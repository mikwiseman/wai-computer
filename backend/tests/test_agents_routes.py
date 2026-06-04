"""Agent definition and run API routes."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models.agent import AgentRun, AgentStep
from app.models.companion_pending_action import CompanionPendingAction
from app.models.telegram import TelegramAccount


async def test_create_list_start_and_fetch_agent_run(client, auth_headers, db_session):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Daily brief",
            "kind": "daily_brief",
            "trigger_type": "manual",
            "autonomy": "propose",
            "config": {"steps": [{"tool": "note", "args": {"text": "hello"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    listed = await client.get("/api/agents", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [a["id"] for a in listed.json()["agents"]] == [agent_id]

    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"trigger_payload": {"objective": "make a brief"}, "run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_body = started.json()
    assert run_body["status"] == "done"
    assert run_body["trigger_payload"] == {"objective": "make a brief"}

    detail = await client.get(
        f"/api/agents/{agent_id}/runs/{run_body['id']}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "done"

    steps = await client.get(
        f"/api/agents/{agent_id}/runs/{run_body['id']}/steps",
        headers=auth_headers,
    )
    assert steps.status_code == 200, steps.text
    assert [s["kind"] for s in steps.json()["steps"]] == [
        "plan",
        "tool_call",
        "tool_result",
        "verify",
        "final",
    ]


async def test_agent_capabilities_are_discoverable(client, auth_headers):
    response = await client.get("/api/agents/capabilities", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    ids = {capability["id"] for capability in body["capabilities"]}
    assert body["schema_version"] == "2026-06-04"
    assert body["max_steps"] >= 1
    assert "wai.search" in ids
    assert "wai.action.propose" in ids
    assert "local.shell" in ids
    contracts = {contract["name"] for contract in body["tool_contracts"]}
    assert "search_wai" in contracts
    assert "desktop_open" in contracts
    shell = next(
        capability for capability in body["capabilities"] if capability["id"] == "local.shell"
    )
    assert shell["availability"] == "planned"
    assert shell["cloud_supported"] is False
    assert shell["permission_scopes"] == ["shell:execute"]


async def test_start_agent_queues_background_run_then_cancel(
    client, auth_headers, db_session, monkeypatch
):
    dispatched: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.agents.enqueue_agent_run",
        lambda run_id: dispatched.append(str(run_id)) or "task-1",
    )
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Queued",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "later"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": False, "idempotency_key": "same-click"},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    assert started.json()["status"] == "pending"
    assert dispatched == [run_id]

    redelivered = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": False, "idempotency_key": "same-click"},
    )
    assert redelivered.status_code == 201, redelivered.text
    assert redelivered.json()["id"] == run_id
    assert dispatched == [run_id]

    cancelled = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/cancel",
        headers=auth_headers,
        json={"reason": "not now"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    run = (
        await db_session.execute(select(AgentRun).where(AgentRun.id == UUID(run_id)))
    ).scalar_one()
    assert run.cancel_requested_at is not None
    steps = (
        await db_session.execute(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.idx)
        )
    ).scalars().all()
    assert [s.kind for s in steps] == ["cancel"]


async def test_start_agent_surfaces_dispatch_failure(
    client, auth_headers, db_session, monkeypatch
):
    from app.core.agent_dispatch import AgentDispatchError

    def fail_dispatch(_run_id):
        raise AgentDispatchError("Could not start agent run")

    monkeypatch.setattr("app.api.routes.agents.enqueue_agent_run", fail_dispatch)
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Queued",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "later"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": False, "idempotency_key": "broker-down"},
    )
    assert started.status_code == 503, started.text
    run = (
        await db_session.execute(
            select(AgentRun).where(
                AgentRun.trigger_key == f"manual:{agent_id}:broker-down"
            )
        )
    ).scalar_one()
    assert run.status == "failed"
    assert run.error == "Could not start agent run"


async def test_inline_agent_guard_failure_returns_429(client, auth_headers, monkeypatch):
    from app.core.agent_guard import AgentGuardError

    async def refuse_budget(_user_id: str) -> None:
        raise AgentGuardError(
            "user_runs",
            "Daily agent-run limit reached for your account.",
            retry_after=123,
        )

    monkeypatch.setattr(
        "app.api.routes.agents.agent_guard.check_run_budget",
        refuse_budget,
    )
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Budgeted",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "blocked"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )

    assert started.status_code == 429, started.text
    assert started.headers["retry-after"] == "123"
    assert started.json()["detail"] == "Daily agent-run limit reached for your account."


async def test_inline_agent_halt_and_concurrency_guard_return_errors(
    client,
    auth_headers,
    monkeypatch,
):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Guarded",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "blocked"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    monkeypatch.setattr(
        "app.api.routes.agents.agent_guard.agents_halted",
        AsyncMock(return_value=True),
    )
    halted = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True, "idempotency_key": "halted"},
    )
    assert halted.status_code == 503
    assert halted.json()["detail"] == "Agents are halted"

    monkeypatch.setattr(
        "app.api.routes.agents.agent_guard.agents_halted",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.api.routes.agents.agent_guard.check_run_budget",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.routes.agents.agent_guard.acquire_run_slot",
        AsyncMock(return_value=None),
    )
    limited = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True, "idempotency_key": "concurrent"},
    )
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Too many concurrent agent runs"


async def test_agent_runs_are_listable(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.agents.enqueue_agent_run",
        lambda run_id: "task-1",
    )
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Listable",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "queued"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": False, "idempotency_key": "list-runs"},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]

    scoped = await client.get(f"/api/agents/{agent_id}/runs", headers=auth_headers)
    assert scoped.status_code == 200, scoped.text
    assert [run["id"] for run in scoped.json()["runs"]] == [run_id]

    scoped_pending = await client.get(
        f"/api/agents/{agent_id}/runs?status=pending",
        headers=auth_headers,
    )
    assert scoped_pending.status_code == 200, scoped_pending.text
    assert [run["id"] for run in scoped_pending.json()["runs"]] == [run_id]

    aggregate = await client.get("/api/agents/runs?status=pending", headers=auth_headers)
    assert aggregate.status_code == 200, aggregate.text
    assert run_id in {run["id"] for run in aggregate.json()["runs"]}


async def test_agent_config_validation_rejects_unknown_tools(client, auth_headers):
    response = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Bad",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "local_shell", "args": {"command": "date"}}]},
        },
    )

    assert response.status_code == 422
    assert "Unknown agent tool" in response.text


async def test_agent_config_validation_rejects_inert_cron_schedule(
    client, auth_headers
):
    missing_interval = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Bad cron",
            "kind": "daily",
            "trigger_type": "cron",
            "config": {"steps": [{"tool": "note", "args": {"text": "tick"}}]},
        },
    )
    assert missing_interval.status_code == 422
    assert "interval_minutes" in missing_interval.text

    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Manual",
            "kind": "daily",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "tick"}}]},
        },
    )
    assert created.status_code == 201, created.text

    inert_update = await client.patch(
        f"/api/agents/{created.json()['id']}",
        headers=auth_headers,
        json={"trigger_type": "cron"},
    )
    assert inert_update.status_code == 422
    assert "interval_minutes" in inert_update.text


async def test_agent_action_reject_resumes_run_as_failed(client, auth_headers):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Messenger",
            "kind": "message",
            "trigger_type": "manual",
            "config": {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "kind": "send",
                            "tool_name": "send_message_telegram",
                            "action_args": {"text": "hello"},
                            "preview": "Send to you: hello",
                            "recipient_display": "you",
                        },
                    },
                    {"tool": "note", "args": {"text": "after send"}},
                ]
            },
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    assert started.json()["status"] == "awaiting_approval"

    actions = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/actions",
        headers=auth_headers,
    )
    assert actions.status_code == 200, actions.text
    action = actions.json()["actions"][0]
    assert action["status"] == "pending"
    assert action["tool"] == "send_message_telegram"

    resolved = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/resolve",
        headers=auth_headers,
        json={"decision": "reject"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "rejected"
    assert resolved.json()["run_status"] == "failed"


async def test_agent_routes_are_owner_scoped(client, auth_headers, db_session):
    # In the per-test schema there are no agents for this freshly registered
    # user unless the route leaks data from another owner.
    listed = await client.get("/api/agents", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["agents"] == []


async def test_agent_update_get_delete_and_disabled_run_conflict(
    client, auth_headers
):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Editable",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "draft"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    patched = await client.patch(
        f"/api/agents/{agent_id}",
        headers=auth_headers,
        json={
            "name": "Edited",
            "enabled": False,
            "config": {"steps": [{"tool": "note", "args": {"text": "edited"}}]},
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Edited"
    assert patched.json()["enabled"] is False

    detail = await client.get(f"/api/agents/{agent_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["config"]["steps"][0]["args"]["text"] == "edited"

    disabled = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert disabled.status_code == 409
    assert disabled.json()["detail"] == "Agent disabled"

    bad_patch = await client.patch(
        f"/api/agents/{agent_id}",
        headers=auth_headers,
        json={"config": {"steps": [{"tool": "local_shell", "args": {}}]}},
    )
    assert bad_patch.status_code == 422

    deleted = await client.delete(f"/api/agents/{agent_id}", headers=auth_headers)
    assert deleted.status_code == 204

    missing = await client.get(f"/api/agents/{agent_id}", headers=auth_headers)
    assert missing.status_code == 404


async def test_agent_run_routes_return_404_for_missing_run(client, auth_headers):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Missing run",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "x"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    run_id = str(uuid4())

    detail = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}",
        headers=auth_headers,
    )
    steps = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/steps",
        headers=auth_headers,
    )
    events = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/events",
        headers=auth_headers,
    )

    assert detail.status_code == 404
    assert steps.status_code == 404
    assert events.status_code == 404


async def test_agent_run_events_stream_terminal_state(client, auth_headers):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Stream",
            "kind": "research",
            "trigger_type": "manual",
            "config": {"steps": [{"tool": "note", "args": {"text": "stream me"}}]},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]

    async with client.stream(
        "GET",
        f"/api/agents/{agent_id}/runs/{run_id}/events",
        headers=auth_headers,
    ) as response:
        body = await response.aread()

    assert response.status_code == 200
    text = body.decode("utf-8")
    assert "event: step" in text
    assert "event: run" in text
    assert '"status": "done"' in text


async def test_aggregate_agent_actions_and_telegram_approval_execute(
    client, auth_headers, db_session, monkeypatch
):
    class FakeTelegramClient:
        async def send_message(self, chat_id: int, text: str):
            return {"message_id": 42, "chat_id": chat_id, "text": text}

    monkeypatch.setattr(
        "app.core.companion_actuators.TelegramBotClient", FakeTelegramClient
    )
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Messenger",
            "kind": "message",
            "trigger_type": "manual",
            "config": {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "kind": "send",
                            "tool_name": "send_message_telegram",
                            "action_args": {"text": "hello from agent"},
                            "preview": "Send to you: hello from agent",
                            "recipient_display": "you",
                        },
                    }
                ]
            },
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    agent = (
        await db_session.execute(
            select(AgentRun).where(AgentRun.agent_id == UUID(agent_id))
        )
    ).scalar_one_or_none()
    assert agent is None

    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True, "idempotency_key": "approve-send"},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    run = (
        await db_session.execute(select(AgentRun).where(AgentRun.id == UUID(run_id)))
    ).scalar_one()
    db_session.add(
        TelegramAccount(
            user_id=run.user_id,
            telegram_user_id=9001,
            telegram_chat_id=9002,
        )
    )
    await db_session.flush()

    aggregate = await client.get("/api/agents/actions", headers=auth_headers)
    assert aggregate.status_code == 200, aggregate.text
    action = aggregate.json()["actions"][0]
    assert action["agent_id"] == agent_id
    assert action["run_id"] == run_id
    assert action["status"] == "pending"
    assert action["preview"] == "Send Telegram message to your linked chat: hello from agent"

    resolved = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/resolve",
        headers=auth_headers,
        json={"decision": "once", "edited_args": {"text": "edited hello"}},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "executed"
    assert resolved.json()["run_status"] == "done"

    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.id == UUID(action["id"])
            )
        )
    ).scalar_one()
    assert row.status == "executed"
    assert row.receipt == {"channel": "telegram", "chat_id": 9002, "message_id": 42}


async def test_agent_approval_surfaces_actuation_error(
    client, auth_headers, db_session
):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Needs telegram",
            "kind": "message",
            "trigger_type": "manual",
            "config": {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "kind": "send",
                            "tool_name": "send_message_telegram",
                            "action_args": {"text": "hello"},
                            "preview": "Send to you: hello",
                        },
                    }
                ]
            },
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    actions = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/actions",
        headers=auth_headers,
    )
    action_id = actions.json()["actions"][0]["id"]

    resolved = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action_id}/resolve",
        headers=auth_headers,
        json={"decision": "once"},
    )

    assert resolved.status_code == 400
    assert resolved.headers["x-agent-run-status"] == "failed"
    assert resolved.json()["detail"] == "No linked Telegram account for this user"
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.id == UUID(action_id)
            )
        )
    ).scalar_one()
    run = (
        await db_session.execute(select(AgentRun).where(AgentRun.id == UUID(run_id)))
    ).scalar_one()
    assert row.status == "failed"
    assert row.receipt == {"error": "No linked Telegram account for this user"}
    assert run.status == "failed"


async def test_desktop_action_dispatch_and_result_resume_run(
    client, auth_headers, db_session
):
    heartbeat = await client.post(
        "/api/devices/heartbeat",
        headers=auth_headers,
        json={"platform": "macos", "name": "Agent Mac"},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    device_id = heartbeat.json()["device_id"]
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Desktop",
            "kind": "mac_edge",
            "trigger_type": "manual",
            "config": {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "kind": "desktop_action",
                            "tool_name": "desktop_open",
                            "action_args": {"target": "https://wai.computer"},
                            "preview": "Open wai.computer",
                            "device_target": device_id,
                        },
                    }
                ]
            },
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    actions = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/actions",
        headers=auth_headers,
    )
    action = actions.json()["actions"][0]
    assert action["kind"] == "desktop_action"

    missing_action = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{uuid4()}/resolve",
        headers=auth_headers,
        json={"decision": "once"},
    )
    assert missing_action.status_code == 404

    missing_desktop_action = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{uuid4()}/desktop_result",
        headers=auth_headers,
        json={"device_id": device_id, "status": "executed"},
    )
    assert missing_desktop_action.status_code == 404

    missing_device = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={"device_id": str(uuid4()), "status": "executed"},
    )
    assert missing_device.status_code == 404

    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.id == UUID(action["id"])
            )
        )
    ).scalar_one()
    row.device_target = None
    await db_session.flush()
    untargeted = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={"device_id": device_id, "status": "executed"},
    )
    assert untargeted.status_code == 409
    row.device_target = device_id
    await db_session.flush()

    other_heartbeat = await client.post(
        "/api/devices/heartbeat",
        headers=auth_headers,
        json={"platform": "macos", "name": "Other Agent Mac"},
    )
    assert other_heartbeat.status_code == 200, other_heartbeat.text
    wrong_device = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={
            "device_id": other_heartbeat.json()["device_id"],
            "status": "executed",
        },
    )
    assert wrong_device.status_code == 409

    premature = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={"device_id": device_id, "status": "executed"},
    )
    assert premature.status_code == 409

    approved = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/resolve",
        headers=auth_headers,
        json={"decision": "once"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "dispatched"
    assert approved.json()["run_status"] == "awaiting_approval"

    result = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={
            "device_id": device_id,
            "status": "executed",
            "payload": {"event_id": "mac-ok"},
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "executed"
    assert result.json()["run_status"] == "done"

    duplicate = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={
            "device_id": device_id,
            "status": "executed",
            "payload": {"event_id": "mac-ok"},
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "executed"

    conflicting_duplicate = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/desktop_result",
        headers=auth_headers,
        json={"device_id": device_id, "status": "failed"},
    )
    assert conflicting_duplicate.status_code == 409

    terminal_resolve = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action['id']}/resolve",
        headers=auth_headers,
        json={"decision": "once"},
    )
    assert terminal_resolve.status_code == 409

    await db_session.refresh(row)
    assert row.receipt == {"event_id": "mac-ok"}


async def test_agent_action_resolve_surfaces_expired_approval(
    client,
    auth_headers,
    db_session,
):
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Expiring",
            "kind": "message",
            "trigger_type": "manual",
            "config": {
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
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    actions = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/actions",
        headers=auth_headers,
    )
    action_id = actions.json()["actions"][0]["id"]
    row = (
        await db_session.execute(
            select(CompanionPendingAction).where(
                CompanionPendingAction.id == UUID(action_id)
            )
        )
    ).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    resolved = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action_id}/resolve",
        headers=auth_headers,
        json={"decision": "once"},
    )

    assert resolved.status_code == 410
    assert resolved.json()["detail"] == "Approval window elapsed (timeout == deny)"
    await db_session.refresh(row)
    assert row.status == "expired"


async def test_desktop_action_failed_result_is_idempotent(
    client,
    auth_headers,
):
    heartbeat = await client.post(
        "/api/devices/heartbeat",
        headers=auth_headers,
        json={"platform": "macos", "name": "Failing Agent Mac"},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    device_id = heartbeat.json()["device_id"]
    created = await client.post(
        "/api/agents",
        headers=auth_headers,
        json={
            "name": "Desktop failure",
            "kind": "mac_edge",
            "trigger_type": "manual",
            "config": {
                "steps": [
                    {
                        "tool": "propose_action",
                        "args": {
                            "kind": "desktop_action",
                            "tool_name": "desktop_open",
                            "action_args": {"target": "https://wai.computer"},
                            "preview": "Open wai.computer",
                            "device_target": device_id,
                        },
                    }
                ]
            },
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    started = await client.post(
        f"/api/agents/{agent_id}/runs",
        headers=auth_headers,
        json={"run_inline": True},
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    actions = await client.get(
        f"/api/agents/{agent_id}/runs/{run_id}/actions",
        headers=auth_headers,
    )
    action_id = actions.json()["actions"][0]["id"]
    approved = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action_id}/resolve",
        headers=auth_headers,
        json={"decision": "once"},
    )
    assert approved.status_code == 200, approved.text

    failed = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action_id}/desktop_result",
        headers=auth_headers,
        json={"device_id": device_id, "status": "failed"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["run_status"] == "failed"

    duplicate = await client.post(
        f"/api/agents/{agent_id}/runs/{run_id}/actions/{action_id}/desktop_result",
        headers=auth_headers,
        json={"device_id": device_id, "status": "refused"},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "failed"
