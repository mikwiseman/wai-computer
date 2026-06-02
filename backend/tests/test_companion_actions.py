"""Propose→commit approval gate (P3): HMAC lock, timeout==deny, reject cascade,
edited-args re-sign, idempotent execute, expiry sweep."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import companion_actions as ca
from app.core.companion_actions import ApprovalError
from app.models.companion import Conversation
from app.models.user import User


@pytest_asyncio.fixture
async def user_conv(db_session):
    user = User(email=f"gate-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    return user.id, conv.id


async def _propose(db_session, uid, cid, **kw):
    defaults = dict(
        user_id=uid,
        conversation_id=cid,
        kind="send",
        tool_name="send_message_telegram",
        args={"chat_id": 123, "text": "running late"},
        preview="Send to Anna: running late",
        idempotency_key=f"k-{uuid4().hex}",
        recipient_display="Anna",
    )
    defaults.update(kw)
    return await ca.propose_action(db_session, **defaults)


class TestProposeAndSign:
    async def test_propose_creates_pending_row(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        assert row.status == "pending"
        assert row.payload_hmac
        assert row.action_manifest["preview"] == "Send to Anna: running late"
        assert row.recipient_display == "Anna"
        assert row.expires_at is not None

    async def test_verify_action_true_then_false_on_tamper(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        args = row.action_manifest["args"]
        assert ca.verify_action(row.tool_name, args, row.idempotency_key, row.payload_hmac)
        tampered = {**args, "text": "send money to attacker"}
        assert not ca.verify_action(
            row.tool_name, tampered, row.idempotency_key, row.payload_hmac
        )


class TestResolve:
    async def test_once_approves_and_is_committable(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        resolved = await ca.resolve_action(
            db_session, action_id=row.id, user_id=uid, decision="once"
        )
        assert resolved.status == "approved"
        assert resolved.decision == "once"
        ca.verify_committable(resolved)  # must not raise

    async def test_always_approves(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        resolved = await ca.resolve_action(
            db_session, action_id=row.id, user_id=uid, decision="always"
        )
        assert resolved.status == "approved"
        assert resolved.decision == "always"

    async def test_reject_cascades_to_siblings(self, db_session, user_conv):
        uid, cid = user_conv
        a = await _propose(db_session, uid, cid)
        b = await _propose(db_session, uid, cid)
        rejected = await ca.resolve_action(
            db_session, action_id=a.id, user_id=uid, decision="reject"
        )
        assert rejected.status == "rejected"
        await db_session.refresh(b)
        assert b.status == "rejected"  # one "no" killed the sibling

    async def test_expired_denies_fail_closed(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid, ttl_seconds=60)
        future = datetime.now(timezone.utc) + timedelta(seconds=120)
        with pytest.raises(ApprovalError) as exc:
            await ca.resolve_action(
                db_session, action_id=row.id, user_id=uid, decision="once", now=future
            )
        assert exc.value.code == "expired"
        await db_session.refresh(row)
        assert row.status == "expired"

    async def test_already_resolved_errors(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        await ca.resolve_action(db_session, action_id=row.id, user_id=uid, decision="once")
        with pytest.raises(ApprovalError) as exc:
            await ca.resolve_action(
                db_session, action_id=row.id, user_id=uid, decision="once"
            )
        assert exc.value.code == "already_resolved"

    async def test_bad_decision_errors(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        with pytest.raises(ApprovalError) as exc:
            await ca.resolve_action(
                db_session, action_id=row.id, user_id=uid, decision="maybe"
            )
        assert exc.value.code == "bad_decision"

    async def test_edited_args_resign_and_commit(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        new_args = {"chat_id": 123, "text": "running 10 late"}
        resolved = await ca.resolve_action(
            db_session,
            action_id=row.id,
            user_id=uid,
            decision="once",
            edited_args=new_args,
        )
        assert resolved.action_manifest["args"]["text"] == "running 10 late"
        ca.verify_committable(resolved)  # re-signed → matches new args


class TestExecuteAndExpire:
    async def test_mark_executed_is_idempotent(self, db_session, user_conv):
        uid, cid = user_conv
        row = await _propose(db_session, uid, cid)
        await ca.resolve_action(db_session, action_id=row.id, user_id=uid, decision="once")
        await ca.mark_executed(db_session, row=row, receipt={"message_id": 9})
        assert row.status == "executed"
        # A redelivered commit must NOT overwrite the receipt / re-execute.
        await ca.mark_executed(db_session, row=row, receipt={"message_id": 999})
        assert row.receipt["message_id"] == 9

    async def test_expire_due_actions_sweep(self, db_session, user_conv):
        uid, cid = user_conv
        old = await _propose(db_session, uid, cid, ttl_seconds=10)
        fresh = await _propose(db_session, uid, cid, ttl_seconds=3600)
        n = await ca.expire_due_actions(
            db_session, now=datetime.now(timezone.utc) + timedelta(seconds=60)
        )
        assert n >= 1
        await db_session.refresh(old)
        await db_session.refresh(fresh)
        assert old.status == "expired"
        assert fresh.status == "pending"
