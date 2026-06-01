"""Pending-action ledger for the propose→commit approval gate.

One row per mutating action the brain proposes (a Telegram/email send, an
external write, or a macOS desktop action). The side effect runs ONLY after an
explicit `/resolve` decision; on timeout the row expires == deny (fail closed).
The same row doubles as the Mac-offline desktop-action queue (`device_target` +
`expires_at`). `action_manifest` MAY carry the recipient/body — it stays in
Postgres only and is NEVER logged raw (privacy-safe logging, AGENTS.md).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CompanionPendingAction(Base, UUIDMixin, TimestampMixin):
    """A proposed, not-yet-executed mutating action awaiting approval."""

    __tablename__ = "companion_pending_actions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The chat turn this action belongs to (null for agent-run-originated
    # actions until the agents tables land in P6).
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # 'send' | 'mutate' | 'desktop_action'
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # tool + normalized args + human-readable dry-run preview + optional
    # undo_token. Source of truth for the committed payload.
    action_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # HMAC(server_secret, canonical_json(tool, args) || idempotency_key),
    # re-verified at commit so an edited/forged payload cannot be approved.
    payload_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    # run_id:step_idx:kind (agents) or conversation:turn:tool (chat). Commit is
    # a no-op if this key already has a receipt — effectively-once side effects.
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # pending | approved | rejected | expired | executed | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending", index=True
    )
    # Approval timeout AND Mac-offline queue TTL. timeout == deny (fail closed).
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Which device must consume a desktop_action (null for cloud sends).
    device_target: Mapped[str | None] = mapped_column(String(120))
    # Resolved recipient display name shown in the confirm sheet (never a raw id).
    recipient_display: Mapped[str | None] = mapped_column(String(200))
    # once | always | reject
    decision: Mapped[str | None] = mapped_column(String(20))
    # Decision/execution evidence = the step's durable result.
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_companion_pending_actions_idempotency"
        ),
    )
