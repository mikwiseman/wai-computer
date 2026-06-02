"""Registered client devices + presence for the Mac-edge channel.

A device (e.g. the user's Mac) heartbeats to advertise reachability; the cloud
uses ``last_seen_at`` to decide whether an approved desktop action can be
dispatched now, queued to its TTL, or must fail loudly (the offline contract).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Device(Base, UUIDMixin, TimestampMixin):
    """A client device that can execute desktop actions (currently macOS)."""

    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'macos' | 'ios' | 'windows' | 'linux'
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform", "name", name="uq_devices_user_platform_name"
        ),
    )
