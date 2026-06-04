"""Generated summary audio artifact models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.recording import Recording
    from app.models.user import User


class SummaryAudioStatus(str, enum.Enum):
    """Lifecycle states for generated summary audio artifacts."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SummaryAudioArtifact(Base, UUIDMixin, TimestampMixin):
    """Durable server-generated audio for a recording or item summary."""

    __tablename__ = "summary_audio_artifacts"
    __table_args__ = (
        CheckConstraint(
            "(recording_id IS NOT NULL AND item_id IS NULL AND source_kind = 'recording') OR "
            "(recording_id IS NULL AND item_id IS NOT NULL AND source_kind = 'item')",
            name="ck_summary_audio_exactly_one_source",
        ),
        Index("ix_summary_audio_artifacts_user_id", "user_id"),
        Index("ix_summary_audio_artifacts_recording_id", "recording_id"),
        Index("ix_summary_audio_artifacts_item_id", "item_id"),
        Index("ix_summary_audio_artifacts_status", "status"),
        Index("ix_summary_audio_artifacts_user_requested", "user_id", "requested_at"),
        Index(
            "ux_summary_audio_active_recording",
            "recording_id",
            unique=True,
            postgresql_where=text("recording_id IS NOT NULL AND status IN ('queued', 'running')"),
        ),
        Index(
            "ux_summary_audio_active_item",
            "item_id",
            unique=True,
            postgresql_where=text("item_id IS NOT NULL AND status IN ('queued', 'running')"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recordings.id", ondelete="CASCADE"), nullable=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SummaryAudioStatus.QUEUED.value,
        server_default=SummaryAudioStatus.QUEUED.value,
    )
    stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    summary_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    storage_path: Mapped[str | None] = mapped_column(String(1000))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    task_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    user: Mapped["User"] = relationship("User")
    recording: Mapped["Recording | None"] = relationship(
        "Recording", back_populates="summary_audio_artifacts"
    )
    item: Mapped["Item | None"] = relationship(
        "Item", back_populates="summary_audio_artifacts"
    )
