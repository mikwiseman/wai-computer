"""Commitment model — persistent storage for tracked promises.

Stores bi-directional commitments detected from conversations:
- What the user promised others
- What others promised the user
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Commitment(Base, UUIDMixin, TimestampMixin):
    """A tracked promise between the user and someone else."""

    __tablename__ = "commitments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    who: Mapped[str] = mapped_column(String(200), nullable=False)
    what: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # i_promised, they_promised, mutual
    deadline: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open"
    )  # open, completed, overdue, cancelled
    source_context: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_commitments_user_status", "user_id", "status"),
        Index("ix_commitments_user_direction", "user_id", "direction"),
    )
