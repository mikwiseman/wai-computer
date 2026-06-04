"""One shared resolve→execute path for a pending companion action.

The web companion route, the Telegram `/approve` command, and the Telegram
inline button all call THIS, so the approval semantics — reject cascade, HMAC
re-verify, desktop dispatch vs server execute, idempotent receipt — cannot drift
between surfaces.

It does NOT commit and does NOT resume agent runs: the caller owns the
transaction boundary, and run-resume differs per surface (only some surfaces and
only agent-originated actions resume a journalled run). Errors surface (no silent
fallback): `ApprovalError` for resolve/verify failures, `ActuationError` for a
side-effect failure (after the row is marked failed).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.companion_actions import (
    ApprovalError,
    mark_executed,
    mark_failed,
    resolve_action,
    verify_committable,
)
from app.core.companion_actuators import ActuationError, execute_action
from app.models.companion_pending_action import CompanionPendingAction


@dataclass
class ResolveOutcome:
    """Result of resolving one pending action."""

    status: str  # "executed" | "rejected" | "dispatched"
    row: CompanionPendingAction
    recipient: str | None


async def resolve_action_for_user(
    db: AsyncSession,
    *,
    action_id: uuid.UUID,
    user_id: uuid.UUID,
    decision: str,
    edited_args: dict[str, Any] | None = None,
) -> ResolveOutcome:
    """Apply the human decision and run the side effect exactly once.

    - reject → cascade-reject siblings, return ``rejected``.
    - desktop_action → re-verify, return ``dispatched`` (the Mac edge drains it
      and reports back via /desktop_result; not run server-side here).
    - otherwise → re-verify, execute server-side, record an idempotent receipt,
      return ``executed``.

    Caller commits. Raises ``ApprovalError`` (resolve/verify) or
    ``ActuationError`` (side-effect failure, with the row already marked failed).
    """
    row = await resolve_action(
        db,
        action_id=action_id,
        user_id=user_id,
        decision=decision,
        edited_args=edited_args,
    )
    if decision == "reject":
        return ResolveOutcome("rejected", row, row.recipient_display)

    # Approved (once/always): re-verify the locked payload, then run it once.
    try:
        verify_committable(row)
        if row.kind == "desktop_action":
            return ResolveOutcome("dispatched", row, row.recipient_display)
        args = (row.action_manifest or {}).get("args") or {}
        receipt = await execute_action(
            db, user_id=user_id, tool_name=row.tool_name, args=args
        )
        await mark_executed(db, row=row, receipt=receipt)
    except (ApprovalError, ActuationError) as exc:
        # Tamper (verify) or side-effect failure → fail closed, then surface.
        await mark_failed(db, row=row, detail=exc.message)
        raise
    return ResolveOutcome("executed", row, row.recipient_display)
