"""Mac-edge desktop-action channel: /resolve dispatch (not server-run), device
drain, result back-channel, and the no-approval-bypass guard."""

import uuid
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.companion_actions import propose_action
from app.models.agent import Agent, AgentRun
from app.models.companion import Conversation


async def _user_id(client, headers) -> uuid.UUID:
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return uuid.UUID(me.json()["id"])


async def _device_id(client, headers, name: str = "Mac") -> str:
    r = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": name},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["device_id"]


async def _desktop_pending(db_session, uid, cid, **kw):
    defaults = dict(
        user_id=uid,
        conversation_id=cid,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "mailto:anna@example.com"},
        preview="Open a new email",
        idempotency_key=f"k-{uuid4().hex}",
    )
    defaults.update(kw)
    row = await propose_action(db_session, **defaults)
    await db_session.flush()
    return row


async def _new_conv(db_session, uid):
    conv = Conversation(user_id=uid)
    db_session.add(conv)
    await db_session.flush()
    return conv.id


async def test_resolve_dispatches_desktop_action_not_server_executed(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid, device_target=device_id)
    r = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dispatched"
    await db_session.refresh(row)
    assert row.status == "approved"  # queued for the device, not server-executed


async def test_drain_and_report_roundtrip(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid, device_target=device_id)
    await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )

    drained = await client.get(
        f"/api/devices/{device_id}/desktop-actions", headers=auth_headers
    )
    assert drained.status_code == 200, drained.text
    actions = drained.json()["actions"]
    item = next(a for a in actions if a["action_id"] == str(row.id))
    assert item["tool"] == "desktop_open"
    # The drained item carries its conversation so the Mac can report back
    # without out-of-band state.
    assert item["chat_id"] == str(cid)

    reported = await client.post(
        f"/api/companion/chats/{item['chat_id']}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed", "payload": {"ok": True}},
        headers=auth_headers,
    )
    assert reported.status_code == 200, reported.text
    await db_session.refresh(row)
    assert row.status == "executed"
    assert row.receipt == {"ok": True}

    # Once executed it drops out of the device's queue.
    again = await client.get(
        f"/api/devices/{device_id}/desktop-actions", headers=auth_headers
    )
    assert all(a["action_id"] != str(row.id) for a in again.json()["actions"])


async def test_drain_agent_desktop_action_carries_agent_report_target(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    agent = Agent(user_id=uid, name="Desktop agent", kind="desktop", trigger_type="manual")
    db_session.add(agent)
    await db_session.flush()
    run = AgentRun(
        agent_id=agent.id,
        user_id=uid,
        trigger_key=f"manual:{agent.id}:{uuid4().hex}",
        trigger_kind="manual",
    )
    db_session.add(run)
    await db_session.flush()
    row = await propose_action(
        db_session,
        user_id=uid,
        conversation_id=None,
        agent_run_id=run.id,
        agent_step_idx=1,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "mailto:anna@example.com"},
        preview="Open a new email",
        idempotency_key=f"k-{uuid4().hex}",
        device_target=device_id,
    )
    row.status = "approved"
    await db_session.flush()

    drained = await client.get(
        f"/api/devices/{device_id}/desktop-actions", headers=auth_headers
    )
    assert drained.status_code == 200, drained.text
    action = next(a for a in drained.json()["actions"] if a["action_id"] == str(row.id))
    assert action["chat_id"] is None
    assert action["agent_id"] == str(agent.id)
    assert action["agent_run_id"] == str(run.id)


async def test_expired_approved_desktop_action_is_not_drained(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid, device_target=device_id)
    row.status = "approved"
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    drained = await client.get(
        f"/api/devices/{device_id}/desktop-actions", headers=auth_headers
    )
    assert drained.status_code == 200, drained.text
    assert all(a["action_id"] != str(row.id) for a in drained.json()["actions"])
    await db_session.refresh(row)
    assert row.status == "expired"


async def test_untargeted_desktop_action_is_not_drained_or_reportable(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid)
    row.status = "approved"
    await db_session.flush()

    drained = await client.get(
        f"/api/devices/{device_id}/desktop-actions", headers=auth_headers
    )
    assert drained.status_code == 200, drained.text
    assert all(a["action_id"] != str(row.id) for a in drained.json()["actions"])

    reported = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert reported.status_code == 409, reported.text
    assert reported.json()["detail"] == "Desktop action has no target device"


async def test_result_on_unapproved_action_rejected(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(
        db_session, uid, cid, device_target=device_id
    )  # still pending, never approved
    res = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert res.status_code == 409, res.text  # cannot mark an unapproved action done
    await db_session.refresh(row)
    assert row.status == "pending"


async def test_failed_report_marks_failed(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid, device_target=device_id)
    await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    res = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "failed"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    await db_session.refresh(row)
    assert row.status == "failed"


async def test_terminal_desktop_reports_are_immutable(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    device_id = await _device_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid, device_target=device_id)
    await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    executed = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed", "payload": {"ok": True}},
        headers=auth_headers,
    )
    assert executed.status_code == 200, executed.text
    duplicate = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed", "payload": {"ok": True}},
        headers=auth_headers,
    )
    assert duplicate.status_code == 200, duplicate.text
    flip = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "failed"},
        headers=auth_headers,
    )
    assert flip.status_code == 409, flip.text
    await db_session.refresh(row)
    assert row.status == "executed"
    assert row.receipt == {"ok": True}


async def test_targeted_desktop_action_requires_matching_device(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    target_device_id = await _device_id(client, auth_headers, name="Target Mac")
    other_device_id = await _device_id(client, auth_headers, name="Other Mac")
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(
        db_session,
        uid,
        cid,
        device_target=target_device_id,
    )
    await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )

    other_queue = await client.get(
        f"/api/devices/{other_device_id}/desktop-actions", headers=auth_headers
    )
    assert other_queue.status_code == 200, other_queue.text
    assert all(a["action_id"] != str(row.id) for a in other_queue.json()["actions"])

    wrong_report = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": other_device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert wrong_report.status_code == 409, wrong_report.text

    target_queue = await client.get(
        f"/api/devices/{target_device_id}/desktop-actions", headers=auth_headers
    )
    assert target_queue.status_code == 200, target_queue.text
    assert any(a["action_id"] == str(row.id) for a in target_queue.json()["actions"])

    reported = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"device_id": target_device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert reported.status_code == 200, reported.text
