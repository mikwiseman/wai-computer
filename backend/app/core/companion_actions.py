"""The propose→commit approval gate.

The single host-owned chokepoint every *mutating* tool routes through (Telegram/
email send, external write, desktop action). Properties (all enforced in CODE,
never by a prompt):

* **register-before-surface** — the pending row is written FIRST, so an approve
  can never race an unregistered id;
* **HMAC payload lock** — ``HMAC(server_secret, fingerprint || idempotency_key)``
  is stored at propose-time and re-verified at commit, so an edited/injected
  payload cannot be approved as something else;
* **idempotency** — one receipt per ``idempotency_key`` ⇒ effectively-once side
  effects across retries/redelivery;
* **timeout == deny** — an unresolved action expires to ``denied`` (fail closed),
  which is the no-fallbacks-correct default even when the user is away;
* **reject cascades** — one "no" kills all sibling pending actions in the turn.

This module only transitions state + validates; the *caller* executes the side
effect after ``resolve_action`` returns an approved row, then calls
``mark_executed`` with a receipt.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.tool_safety import build_action_fingerprint
from app.models.companion_pending_action import CompanionPendingAction

# Approval window. After this, the action is denied (fail closed).
DEFAULT_TTL_SECONDS = 300

_PENDING = "pending"
_APPROVED = "approved"
_REJECTED = "rejected"
_EXPIRED = "expired"
_EXECUTED = "executed"
_FAILED = "failed"

_VALID_DECISIONS = frozenset({"once", "always", "reject"})


def _preview_value(value: Any, *, max_length: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}..."


def canonical_action_preview(tool_name: str, args: dict[str, Any] | None) -> str:
    """Build the approval text from the signed tool args, never model/config copy."""
    args = args or {}
    if tool_name in {"send_message_telegram", "reply_to_message_telegram"}:
        text = _preview_value(args.get("text"))
        return f"Send Telegram message to your linked chat: {text}"
    if tool_name == "desktop_open":
        target = _preview_value(args.get("target"))
        return f"Open on your Mac: {target}"
    if tool_name == "desktop_type":
        text = _preview_value(args.get("text"))
        return f"Type on your Mac: {text}"
    if tool_name == "desktop_click":
        return f"Click desktop element #{args.get('index')}"
    if tool_name == "desktop_snapshot":
        return "Capture a desktop UI snapshot"
    return f"Run {tool_name} with approved arguments"


class ApprovalError(Exception):
    """Raised when a pending action cannot be resolved/committed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _hmac_secret() -> bytes:
    # Server-side secret that never leaves the backend.
    return get_settings().jwt_secret.encode("utf-8")


def sign_action(tool: str, args: dict[str, Any] | None, idempotency_key: str) -> str:
    """HMAC over (content-addressed payload, idempotency_key)."""
    fingerprint = build_action_fingerprint(tool, args)
    message = f"{fingerprint}:{idempotency_key}".encode("utf-8")
    return hmac.new(_hmac_secret(), message, hashlib.sha256).hexdigest()


def verify_action(
    tool: str, args: dict[str, Any] | None, idempotency_key: str, signature: str
) -> bool:
    """Constant-time check that (tool, args, key) still matches the signature."""
    expected = sign_action(tool, args, idempotency_key)
    return hmac.compare_digest(expected, signature or "")


async def propose_action(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    agent_run_id: uuid.UUID | None = None,
    agent_step_idx: int | None = None,
    kind: str,
    tool_name: str,
    args: dict[str, Any],
    preview: str,
    idempotency_key: str,
    recipient_display: str | None = None,
    device_target: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> CompanionPendingAction:
    """Register a pending action (status=pending). The side effect is NOT run.

    The caller emits the ``ActionProposedEvent`` AFTER this returns so the row
    is guaranteed to exist before the client can resolve it.
    """
    now = now or datetime.now(timezone.utc)
    manifest = {
        "tool": tool_name,
        "args": args,
        "preview": canonical_action_preview(tool_name, args),
    }
    row = CompanionPendingAction(
        user_id=user_id,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        agent_step_idx=agent_step_idx,
        kind=kind,
        tool_name=tool_name,
        action_manifest=manifest,
        payload_hmac=sign_action(tool_name, args, idempotency_key),
        idempotency_key=idempotency_key,
        status=_PENDING,
        expires_at=now + timedelta(seconds=ttl_seconds),
        device_target=device_target,
        recipient_display=recipient_display,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_pending(
    db: AsyncSession, *, action_id: uuid.UUID, user_id: uuid.UUID, lock: bool = True
) -> CompanionPendingAction | None:
    """Owner-scoped load. Locks the row so concurrent resolves serialize."""
    stmt = select(CompanionPendingAction).where(
        CompanionPendingAction.id == action_id,
        CompanionPendingAction.user_id == user_id,
    )
    if lock:
        bind = db.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
            stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def resolve_action(
    db: AsyncSession,
    *,
    action_id: uuid.UUID,
    user_id: uuid.UUID,
    decision: str,
    edited_args: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> CompanionPendingAction:
    """Apply the human decision. Returns the row; does NOT run the side effect.

    once/always → approved (caller executes then mark_executed); reject →
    rejected + cascade to siblings; expired/already-resolved → ApprovalError.
    """
    now = now or datetime.now(timezone.utc)
    if decision not in _VALID_DECISIONS:
        raise ApprovalError("bad_decision", f"Unknown decision: {decision}")

    row = await get_pending(db, action_id=action_id, user_id=user_id)
    if row is None:
        raise ApprovalError("not_found", "Pending action not found")
    if row.status != _PENDING:
        raise ApprovalError("already_resolved", f"Action already {row.status}")
    if row.expires_at <= now:
        row.status = _EXPIRED
        row.resolved_at = now
        await db.flush()
        raise ApprovalError("expired", "Approval window elapsed (timeout == deny)")

    if decision == "reject":
        row.status = _REJECTED
        row.decision = "reject"
        row.resolved_at = now
        await _cascade_reject(db, row, now)
        await db.flush()
        await db.refresh(row)
        return row

    # once | always → approve. Edited args re-sign so commit == approved payload.
    if edited_args is not None:
        manifest = dict(row.action_manifest or {})
        manifest["args"] = edited_args
        manifest["preview"] = canonical_action_preview(row.tool_name, edited_args)
        row.action_manifest = manifest
        row.payload_hmac = sign_action(row.tool_name, edited_args, row.idempotency_key)
    row.status = _APPROVED
    row.decision = decision
    row.resolved_at = now
    await db.flush()
    await db.refresh(row)
    return row


async def _cascade_reject(
    db: AsyncSession, rejected: CompanionPendingAction, now: datetime
) -> None:
    """One 'no' rejects all sibling pending actions in the same chat or agent run."""
    if rejected.conversation_id is None and rejected.agent_run_id is None:
        return
    stmt = update(CompanionPendingAction).where(
        CompanionPendingAction.status == _PENDING,
        CompanionPendingAction.id != rejected.id,
    )
    if rejected.conversation_id is not None:
        stmt = stmt.where(CompanionPendingAction.conversation_id == rejected.conversation_id)
    else:
        stmt = stmt.where(CompanionPendingAction.agent_run_id == rejected.agent_run_id)
    await db.execute(
        stmt.values(status=_REJECTED, decision="reject", resolved_at=now)
    )


def verify_committable(row: CompanionPendingAction) -> None:
    """Re-verify the HMAC before executing — the committed action must be exactly
    the approved one. Raises on tamper."""
    args = (row.action_manifest or {}).get("args")
    if not verify_action(row.tool_name, args, row.idempotency_key, row.payload_hmac):
        raise ApprovalError("payload_tampered", "Action payload changed after approval")


async def mark_executed(
    db: AsyncSession, *, row: CompanionPendingAction, receipt: dict[str, Any]
) -> CompanionPendingAction:
    """Record the side-effect receipt. Idempotent: a second call is a no-op so a
    redelivered commit cannot double-execute."""
    if row.status == _EXECUTED:
        return row
    if row.status in {_FAILED, _REJECTED, _EXPIRED}:
        raise ApprovalError("already_resolved", f"Action already {row.status}")
    if row.status != _APPROVED:
        raise ApprovalError("not_approved", f"Action is {row.status}, not approved")
    row.status = _EXECUTED
    row.receipt = receipt
    await db.flush()
    await db.refresh(row)
    return row


async def mark_failed(
    db: AsyncSession, *, row: CompanionPendingAction, detail: str
) -> CompanionPendingAction:
    if row.status == _FAILED:
        return row
    if row.status == _EXECUTED:
        raise ApprovalError("already_resolved", "Action already executed")
    row.status = _FAILED
    row.receipt = {"error": detail}
    await db.flush()
    await db.refresh(row)
    return row


async def expire_due_actions(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Sweep pending/approved rows past their TTL to expired (timeout == deny).

    Approved desktop actions stay in the Mac offline queue until a device
    reports them executed; their ``expires_at`` is still authoritative. Once the
    queue TTL passes, they must fail closed instead of remaining executable.
    Returns the number expired.
    """
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(CompanionPendingAction)
        .where(
            CompanionPendingAction.status.in_([_PENDING, _APPROVED]),
            CompanionPendingAction.expires_at <= now,
        )
        .values(status=_EXPIRED, resolved_at=now)
    )
    return result.rowcount or 0


async def expire_actions_for_run(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Expire all unresolved action rows for a run.

    Used by cancellation: a cancelled agent run must not leave approved desktop
    work drainable or pending sends approvable later.
    """
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(CompanionPendingAction)
        .where(
            CompanionPendingAction.user_id == user_id,
            CompanionPendingAction.agent_run_id == run_id,
            CompanionPendingAction.status.in_([_PENDING, _APPROVED]),
        )
        .values(status=_EXPIRED, resolved_at=now)
    )
    return result.rowcount or 0
