"""Admin role and audit models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class AdminRole(Base, UUIDMixin, TimestampMixin):
    """An active admin role granted to a WaiComputer user."""

    __tablename__ = "admin_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_admin_roles_user_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    granted_by: Mapped["User | None"] = relationship("User", foreign_keys=[granted_by_user_id])


class AdminAuditLog(Base, UUIDMixin, TimestampMixin):
    """Append-only audit entry for admin-visible mutations."""

    __tablename__ = "admin_audit_logs"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    actor: Mapped["User | None"] = relationship("User")


from app.models.user import User  # noqa: E402
