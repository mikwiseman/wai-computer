"""Memory proposals — the governance queue between raw signal and canonical
memory (wai-brain proposal→review→canonical, adapted).

The nightly consolidator no longer writes durable facts straight into a
user's memory blocks. Instead it emits a ``MemoryProposal`` per durable
update. Low-risk, high-confidence additions auto-accept (applied immediately
via the same ``write_block`` path); destructive corrections or low-confidence
guesses are parked as ``pending`` for one-tap human review. This is the
"mix auto + cherry-pick" governance: raw items stay ground truth, valuable
facts are promoted deliberately.

Design notes:
- ``dedup_key`` is a deterministic SHA-256 over ``(user, block, operation,
  normalised content)``. ``(user_id, dedup_key)`` is unique so the same fact
  is never proposed twice — whether it's still pending, already accepted, or
  was rejected (a reject is durable; we don't nag).
- ``risk`` is derived from the operation: an ``append`` is additive (low),
  while ``replace_line`` / ``rewrite`` overwrite prior truth (high) and always
  route to review regardless of confidence.
- ``evidence`` carries provenance (source recording/item ids + optional quote)
  so the review UI can show *why* a fact was proposed without re-deriving it.
- Free-string ``kind`` / ``risk`` / ``status`` / ``authority`` (no DB enums)
  keep migrations cheap as the governed surface grows beyond block upserts.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class MemoryProposal(Base, UUIDMixin, TimestampMixin):
    """A proposed change to canonical user memory, awaiting auto/human decision."""

    __tablename__ = "memory_proposals"
    __table_args__ = (
        # The same fact is proposed once per user, ever (pending/accepted/rejected).
        UniqueConstraint("user_id", "dedup_key", name="uq_memory_proposals_user_dedup"),
        Index("ix_memory_proposals_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # What is being proposed. kind: memory_upsert (block edit) | ... (future)
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="memory_upsert", server_default="memory_upsert"
    )
    # risk: low (additive append) | high (overwrites prior truth) — drives auto vs review.
    risk: Mapped[str] = mapped_column(String(10), nullable=False, default="low")

    # The block-update payload (kind=memory_upsert).
    block_label: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    target_line: Mapped[str | None] = mapped_column(Text)

    # Human-readable one-liner for the review card.
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5, server_default="0.5"
    )
    # authority: self (user's own material) | connected (MCP tool data) | model (pure inference)
    authority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="self", server_default="self"
    )
    evidence: Mapped[list | None] = mapped_column(JSONB)

    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # status: pending | accepted | rejected | superseded
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    # decided_by: auto (threshold) | user (one-tap review)
    decided_by: Mapped[str | None] = mapped_column(String(20))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User")
