"""Highlight / key-moment model extracted from recording transcripts."""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class Highlight(Base, UUIDMixin):
    """Key moment extracted from a recording transcript during summarization."""

    __tablename__ = "highlights"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(String(100))
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    importance: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    source_segment_ids: Mapped[list | None] = mapped_column(JSONB)

    # Relationships
    recording: Mapped["Recording"] = relationship("Recording", back_populates="highlights")


# Import at bottom to avoid circular imports
from app.models.recording import Recording  # noqa: E402, F811
