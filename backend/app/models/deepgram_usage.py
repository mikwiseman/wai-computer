"""Deepgram usage ledger models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class DeepgramUsageEvent(Base, UUIDMixin):
    """One auditable Deepgram STT attempt, refusal, or provider failure."""

    __tablename__ = "deepgram_usage_events"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="deepgram", server_default="deepgram"
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(32))
    content_type: Mapped[str | None] = mapped_column(String(128))
    audio_seconds: Mapped[float | None] = mapped_column(Float)
    billable_seconds: Mapped[float | None] = mapped_column(Float)
    channel_count: Mapped[int | None] = mapped_column(Integer)
    audio_bytes: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    pricing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unpriced",
        server_default="unpriced",
    )
    billing_mode: Mapped[str | None] = mapped_column(String(32))
    language_mode: Mapped[str | None] = mapped_column(String(32))
    addons: Mapped[list | None] = mapped_column(JSONB)
    price_source: Mapped[str | None] = mapped_column(String(120))
    provider_status_code: Mapped[int | None] = mapped_column(Integer)
    provider_error_code: Mapped[str | None] = mapped_column(String(128))
    guard_code: Mapped[str | None] = mapped_column(String(128))
    error_type: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    task_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict | None] = mapped_column(JSONB)

    user = relationship("User")
    recording = relationship("Recording")

    __table_args__ = (
        Index(
            "ix_deepgram_usage_events_operation_status_created",
            "operation",
            "status",
            "created_at",
        ),
        Index("ix_deepgram_usage_events_user_created", "user_id", "created_at"),
        Index("ix_deepgram_usage_events_recording_created", "recording_id", "created_at"),
    )
