"""Mac-edge desktop-action channel: /resolve dispatch (not server-run), device
drain, result back-channel, and the no-approval-bypass guard."""

import uuid
from uuid import uuid4

from app.core.companion_actions import propose_action
from app.models.companion import Conversation


async def _user_id(client, headers) -> uuid.UUID:
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return uuid.UUID(me.json()["id"])


async def _device_id(client, headers) -> str:
    r = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": "Mac"},
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
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid)
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
    row = await _desktop_pending(db_session, uid, cid)
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
        json={"status": "executed", "payload": {"ok": True}},
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


async def test_result_on_unapproved_action_rejected(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid)  # still pending, never approved
    res = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"status": "executed"},
        headers=auth_headers,
    )
    assert res.status_code == 409, res.text  # cannot mark an unapproved action done
    await db_session.refresh(row)
    assert row.status == "pending"


async def test_failed_report_marks_failed(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    cid = await _new_conv(db_session, uid)
    row = await _desktop_pending(db_session, uid, cid)
    await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    res = await client.post(
        f"/api/companion/chats/{cid}/actions/{row.id}/desktop_result",
        json={"status": "failed"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    await db_session.refresh(row)
    assert row.status == "failed"
