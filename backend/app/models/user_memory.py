"""Long-term memory blocks for the Wai companion.

Two tables:
- user_memory_blocks — one row per (user_id, label). Body is markdown that
  renders into the cacheable system prefix on every turn (Letta core-block
  pattern). Char limits guard the prompt cache size.
- user_memory_log — append-only audit trail keyed by user/label so we can
  trace which conversation or which consolidator pass changed a block, and
  roll back if needed (gbrain log.md pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class UserMemoryBlock(Base, UUIDMixin):
    """A labelled markdown block carrying durable facts about the user."""

    __tablename__ = "user_memory_blocks"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "label", name="uq_user_memory_blocks_user_label"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    char_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # 'agent' (in-turn remember call), 'user' (UI edit), 'consolidator'
    # (nightly sleep-time agent), 'system' (seeding).
    updated_by: Mapped[str] = mapped_column(String(20), nullable=False)


class UserMemoryLogEntry(Base, UUIDMixin):
    """Append-only audit of every write to a memory block."""

    __tablename__ = "user_memory_log"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    # 'append' | 'replace_line' | 'rewrite' | 'seed'
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    before_body: Mapped[str] = mapped_column(Text, nullable=False)
    after_body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
