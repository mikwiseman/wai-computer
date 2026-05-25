"""move admin roles to staff members

Revision ID: 20260525_130000
Revises: 20260525_120000
Create Date: 2026-05-25 13:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260525_130000"
down_revision: Union[str, None] = "20260525_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_staff_members_user_id"),
    )
    op.create_index(op.f("ix_staff_members_user_id"), "staff_members", ["user_id"])
    op.create_index(op.f("ix_staff_members_status"), "staff_members", ["status"])

    op.add_column(
        "admin_roles",
        sa.Column("staff_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "admin_roles",
        sa.Column("granted_by_staff_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.execute(
        """
        INSERT INTO staff_members (user_id, status)
        SELECT DISTINCT user_id, 'active'
        FROM admin_roles
        WHERE user_id IS NOT NULL
        ON CONFLICT (user_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE admin_roles AS role
        SET staff_member_id = staff.id
        FROM staff_members AS staff
        WHERE staff.user_id = role.user_id
        """
    )
    op.execute(
        """
        UPDATE admin_roles AS role
        SET granted_by_staff_member_id = staff.id
        FROM staff_members AS staff
        WHERE staff.user_id = role.granted_by_user_id
        """
    )

    op.alter_column("admin_roles", "staff_member_id", nullable=False)
    op.create_foreign_key(
        "fk_admin_roles_staff_member_id_staff_members",
        "admin_roles",
        "staff_members",
        ["staff_member_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_admin_roles_granted_by_staff_member_id_staff_members",
        "admin_roles",
        "staff_members",
        ["granted_by_staff_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_admin_roles_staff_member_id"), "admin_roles", ["staff_member_id"])
    op.drop_constraint("uq_admin_roles_user_role", "admin_roles", type_="unique")
    op.create_unique_constraint(
        "uq_admin_roles_staff_role", "admin_roles", ["staff_member_id", "role"]
    )

    op.add_column(
        "admin_audit_logs",
        sa.Column("actor_staff_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE admin_audit_logs AS log
        SET actor_staff_member_id = staff.id
        FROM staff_members AS staff
        WHERE staff.user_id = log.actor_user_id
        """
    )
    op.create_foreign_key(
        "fk_admin_audit_logs_actor_staff_member_id_staff_members",
        "admin_audit_logs",
        "staff_members",
        ["actor_staff_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_admin_audit_logs_actor_staff_member_id"),
        "admin_audit_logs",
        ["actor_staff_member_id"],
    )

    op.drop_constraint("admin_roles_granted_by_user_id_fkey", "admin_roles", type_="foreignkey")
    op.drop_constraint("admin_roles_user_id_fkey", "admin_roles", type_="foreignkey")
    op.drop_index(op.f("ix_admin_roles_user_id"), table_name="admin_roles")
    op.drop_column("admin_roles", "granted_by_user_id")
    op.drop_column("admin_roles", "user_id")


def downgrade() -> None:
    op.add_column(
        "admin_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "admin_roles",
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE admin_roles AS role
        SET user_id = staff.user_id
        FROM staff_members AS staff
        WHERE staff.id = role.staff_member_id
        """
    )
    op.execute(
        """
        UPDATE admin_roles AS role
        SET granted_by_user_id = staff.user_id
        FROM staff_members AS staff
        WHERE staff.id = role.granted_by_staff_member_id
        """
    )
    op.alter_column("admin_roles", "user_id", nullable=False)
    op.create_foreign_key(
        "admin_roles_user_id_fkey",
        "admin_roles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "admin_roles_granted_by_user_id_fkey",
        "admin_roles",
        "users",
        ["granted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_admin_roles_user_id"), "admin_roles", ["user_id"])
    op.drop_constraint("uq_admin_roles_staff_role", "admin_roles", type_="unique")
    op.create_unique_constraint("uq_admin_roles_user_role", "admin_roles", ["user_id", "role"])

    op.drop_index(
        op.f("ix_admin_audit_logs_actor_staff_member_id"),
        table_name="admin_audit_logs",
    )
    op.drop_constraint(
        "fk_admin_audit_logs_actor_staff_member_id_staff_members",
        "admin_audit_logs",
        type_="foreignkey",
    )
    op.drop_column("admin_audit_logs", "actor_staff_member_id")

    op.drop_index(op.f("ix_admin_roles_staff_member_id"), table_name="admin_roles")
    op.drop_constraint(
        "fk_admin_roles_granted_by_staff_member_id_staff_members",
        "admin_roles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_admin_roles_staff_member_id_staff_members",
        "admin_roles",
        type_="foreignkey",
    )
    op.drop_column("admin_roles", "granted_by_staff_member_id")
    op.drop_column("admin_roles", "staff_member_id")

    op.drop_index(op.f("ix_staff_members_status"), table_name="staff_members")
    op.drop_index(op.f("ix_staff_members_user_id"), table_name="staff_members")
    op.drop_table("staff_members")
