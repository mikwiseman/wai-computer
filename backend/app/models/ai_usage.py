"""Unified AI/model usage ledger models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class AiUsageEvent(Base, UUIDMixin):
    """One metadata-only AI provider usage event.

    The ledger deliberately stores metrics and correlation IDs, not prompts,
    outputs, transcript text, file names, search queries, or other user content.
    """

    __tablename__ = "ai_usage_events"

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
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
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
    provider_status_code: Mapped[int | None] = mapped_column(Integer)
    provider_error_code: Mapped[str | None] = mapped_column(String(128))
    guard_code: Mapped[str | None] = mapped_column(String(128))
    error_type: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    task_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict | None] = mapped_column(JSONB)

    user = relationship("User")
    recording = relationship("Recording")
    item = relationship("Item")
    conversation = relationship("Conversation")
    message = relationship("ChatMessage")

    __table_args__ = (
        Index("ix_ai_usage_events_provider_created", "provider", "created_at"),
        Index("ix_ai_usage_events_feature_created", "feature", "created_at"),
        Index("ix_ai_usage_events_model_created", "model", "created_at"),
        Index("ix_ai_usage_events_status_created", "status", "created_at"),
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
        Index(
            "ix_ai_usage_events_provider_feature_status_created",
            "provider",
            "feature",
            "status",
            "created_at",
        ),
    )
