"""POST /api/companion/chats/{chat_id}/actions/{action_id}/resolve (P3):
approve→execute-once, reject, timeout==deny (410), not-found (404)."""

import uuid
from uuid import uuid4

import pytest

from app.core import companion_actuators, companion_resolve
from app.core.companion_actions import propose_action
from app.core.companion_actuators import ActuationError
from app.models.companion import Conversation
from app.models.telegram import TelegramAccount
from app.models.user import User


class FakeTelegram:
    sent: list = []

    def __init__(self, token=None):
        pass

    async def send_message(self, chat_id, text, **kw):
        FakeTelegram.sent.append((chat_id, text))
        return {"message_id": 42}


async def _user_id(client, headers) -> uuid.UUID:
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return uuid.UUID(me.json()["id"])


async def _new_conv(db_session, user_id) -> uuid.UUID:
    conv = Conversation(user_id=user_id)
    db_session.add(conv)
    await db_session.flush()
    return conv.id


async def _pending(db_session, user_id, conv_id, **kw):
    defaults = dict(
        user_id=user_id,
        conversation_id=conv_id,
        kind="send",
        tool_name="send_message_telegram",
        args={"text": "running late"},
        preview="Send to you: running late",
        idempotency_key=f"k-{uuid4().hex}",
        recipient_display="you",
    )
    defaults.update(kw)
    row = await propose_action(db_session, **defaults)
    await db_session.flush()
    return row


async def test_resolve_once_executes_send(client, auth_headers, db_session, monkeypatch):
    FakeTelegram.sent = []
    monkeypatch.setattr(companion_actuators, "TelegramBotClient", FakeTelegram)
    uid = await _user_id(client, auth_headers)
    db_session.add(
        TelegramAccount(
            user_id=uid,
            telegram_user_id=int(uuid4().int % 1_000_000_000),
            telegram_chat_id=555,
        )
    )
    conv_id = await _new_conv(db_session, uid)
    row = await _pending(db_session, uid, conv_id)

    r = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "executed"
    assert body["recipient"] == "you"
    assert FakeTelegram.sent == [(555, "running late")]
    await db_session.refresh(row)
    assert row.status == "executed"


async def test_resolve_reject(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    row = await _pending(db_session, uid, conv_id)

    r = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/resolve",
        json={"decision": "reject"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    await db_session.refresh(row)
    assert row.status == "rejected"


async def test_resolve_expired_returns_410(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    # Already past its TTL → resolve must deny (timeout == deny).
    row = await _pending(db_session, uid, conv_id, ttl_seconds=-10)

    r = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert r.status_code == 410, r.text
    await db_session.refresh(row)
    assert row.status == "expired"


async def test_resolve_unknown_action_returns_404(client, auth_headers, db_session):
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    r = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{uuid4()}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text


async def test_resolve_rejects_same_user_action_from_different_chat(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    other_conv_id = await _new_conv(db_session, uid)
    row = await _pending(db_session, uid, conv_id)

    r = await client.post(
        f"/api/companion/chats/{other_conv_id}/actions/{row.id}/resolve",
        json={"decision": "reject"},
        headers=auth_headers,
    )

    assert r.status_code == 404, r.text
    await db_session.refresh(row)
    assert row.status == "pending"


async def test_desktop_result_requires_target_device_and_is_idempotent(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    heartbeat = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": "Companion Mac"},
        headers=auth_headers,
    )
    assert heartbeat.status_code == 200, heartbeat.text
    device_id = heartbeat.json()["device_id"]
    row = await propose_action(
        db_session,
        user_id=uid,
        conversation_id=conv_id,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "https://wai.computer"},
        preview="Open WaiComputer",
        idempotency_key=f"desktop:{uuid4().hex}",
        device_target=device_id,
    )
    await db_session.flush()

    missing_action = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{uuid4()}/desktop_result",
        json={"device_id": device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert missing_action.status_code == 404

    missing_device = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": str(uuid4()), "status": "executed"},
        headers=auth_headers,
    )
    assert missing_device.status_code == 404

    row.device_target = None
    await db_session.flush()
    untargeted = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert untargeted.status_code == 409
    row.device_target = device_id
    await db_session.flush()

    other_heartbeat = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": "Other Companion Mac"},
        headers=auth_headers,
    )
    assert other_heartbeat.status_code == 200, other_heartbeat.text
    wrong_device = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": other_heartbeat.json()["device_id"], "status": "executed"},
        headers=auth_headers,
    )
    assert wrong_device.status_code == 409

    premature = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert premature.status_code == 409

    approved = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "dispatched"

    executed = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={
            "device_id": device_id,
            "status": "executed",
            "payload": {"event_id": "companion-mac-ok"},
        },
        headers=auth_headers,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "executed"

    duplicate = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "executed"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 200, duplicate.text

    conflicting_duplicate = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "failed"},
        headers=auth_headers,
    )
    assert conflicting_duplicate.status_code == 409


async def test_failed_desktop_result_duplicate_is_idempotent(
    client, auth_headers, db_session
):
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    heartbeat = await client.post(
        "/api/devices/heartbeat",
        json={"platform": "macos", "name": "Failing Companion Mac"},
        headers=auth_headers,
    )
    assert heartbeat.status_code == 200, heartbeat.text
    device_id = heartbeat.json()["device_id"]
    row = await propose_action(
        db_session,
        user_id=uid,
        conversation_id=conv_id,
        kind="desktop_action",
        tool_name="desktop_open",
        args={"target": "https://wai.computer"},
        preview="Open WaiComputer",
        idempotency_key=f"desktop:{uuid4().hex}",
        device_target=device_id,
    )
    await db_session.flush()
    approved = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text

    failed = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "failed"},
        headers=auth_headers,
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"

    duplicate_failure = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/desktop_result",
        json={"device_id": device_id, "status": "refused"},
        headers=auth_headers,
    )
    assert duplicate_failure.status_code == 200, duplicate_failure.text
    assert duplicate_failure.json()["status"] == "failed"


async def test_resolve_helper_marks_failed_on_actuation_error(db_session, monkeypatch):
    """The shared helper fails closed: a side-effect error marks the row failed
    and surfaces (no silent fallback)."""
    user = User(email=f"resolve-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv_id = await _new_conv(db_session, user.id)
    row = await _pending(db_session, user.id, conv_id)

    async def boom(*args, **kwargs):
        raise ActuationError("send_failed", "boom")

    monkeypatch.setattr(companion_resolve, "execute_action", boom)

    with pytest.raises(ActuationError):
        await companion_resolve.resolve_action_for_user(
            db_session,
            action_id=row.id,
            user_id=user.id,
            decision="once",
        )
    await db_session.refresh(row)
    assert row.status == "failed"


async def test_resolve_route_reports_actuation_error(
    client, auth_headers, db_session, monkeypatch
):
    """A side-effect failure surfaces as 400 and marks the action failed."""

    async def boom(*args, **kwargs):
        raise ActuationError("send_failed", "boom")

    monkeypatch.setattr(companion_resolve, "execute_action", boom)
    uid = await _user_id(client, auth_headers)
    conv_id = await _new_conv(db_session, uid)
    row = await _pending(db_session, uid, conv_id)

    r = await client.post(
        f"/api/companion/chats/{conv_id}/actions/{row.id}/resolve",
        json={"decision": "once"},
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    await db_session.refresh(row)
    assert row.status == "failed"
