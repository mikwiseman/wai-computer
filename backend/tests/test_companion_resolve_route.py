"""POST /api/companion/chats/{chat_id}/actions/{action_id}/resolve (P3):
approve→execute-once, reject, timeout==deny (410), not-found (404)."""

import uuid
from uuid import uuid4

from app.core import companion_actuators
from app.core.companion_actions import propose_action
from app.models.companion import Conversation
from app.models.telegram import TelegramAccount


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
