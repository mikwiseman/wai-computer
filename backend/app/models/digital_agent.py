"""Digital Agent model — autonomous AI agents created by users.

Each agent has a schedule (cron), tools, and a system prompt.
Agents run via Celery Beat and deliver results through configurable channels.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DigitalAgent(Base, UUIDMixin, TimestampMixin):
    """An autonomous AI agent that runs on a schedule."""

    __tablename__ = "digital_agents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Agent definition
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    tools: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    # Schedule
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)  # cron, manual
    cron_expression: Mapped[str | None] = mapped_column(String(50))

    # Delivery
    delivery_channel: Mapped[str] = mapped_column(
        String(50), nullable=False, default="api"
    )  # api, telegram (Phase 4)
    delivery_target: Mapped[str | None] = mapped_column(String(200))

    # State
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_result: Mapped[str | None] = mapped_column(Text)

    # Limits
    max_tokens_per_run: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)

    __table_args__ = (
        Index("ix_digital_agents_user_status", "user_id", "status"),
        Index("ix_digital_agents_next_run", "next_run_at", "status"),
    )
