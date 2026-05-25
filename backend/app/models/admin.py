"""Staff/admin role and audit models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class StaffMember(Base, UUIDMixin, TimestampMixin):
    """A staff profile attached to a login identity."""

    __tablename__ = "staff_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    roles: Mapped[list["AdminRole"]] = relationship(
        "AdminRole",
        foreign_keys="AdminRole.staff_member_id",
        back_populates="staff_member",
        cascade="all, delete-orphan",
    )


class AdminRole(Base, UUIDMixin, TimestampMixin):
    """An active admin role granted to a staff member."""

    __tablename__ = "admin_roles"
    __table_args__ = (
        UniqueConstraint("staff_member_id", "role", name="uq_admin_roles_staff_role"),
    )

    staff_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    granted_by_staff_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_members.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    staff_member: Mapped["StaffMember"] = relationship(
        "StaffMember", foreign_keys=[staff_member_id], back_populates="roles"
    )
    granted_by: Mapped["StaffMember | None"] = relationship(
        "StaffMember", foreign_keys=[granted_by_staff_member_id]
    )


class AdminAuditLog(Base, UUIDMixin, TimestampMixin):
    """Append-only audit entry for admin-visible mutations."""

    __tablename__ = "admin_audit_logs"

    actor_staff_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    actor_staff_member: Mapped["StaffMember | None"] = relationship("StaffMember")
    actor: Mapped["User | None"] = relationship("User")


from app.models.user import User  # noqa: E402
