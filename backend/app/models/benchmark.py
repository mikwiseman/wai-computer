"""Benchmark-related models."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DictationBenchmarkVote(Base, UUIDMixin, TimestampMixin):
    """User-selected winner from a blind dictation benchmark battle."""

    __tablename__ = "dictation_benchmark_votes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    battle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    selected_candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_model: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
