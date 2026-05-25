"""add admin console roles audit and user lifecycle

Revision ID: 20260525_120000
Revises: 20260522_130000
Create Date: 2026-05-25 12:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260525_120000"
down_revision: Union[str, None] = "20260522_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("account_status", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.add_column("users", sa.Column("account_status_reason", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("account_status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "account_status_changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_users_account_status"), "users", ["account_status"])
    op.create_foreign_key(
        "fk_users_account_status_changed_by_user_id_users",
        "users",
        "users",
        ["account_status_changed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    op.add_column(
        "billing_promo_codes",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_billing_promo_codes_archived_at"),
        "billing_promo_codes",
        ["archived_at"],
    )

    op.create_table(
        "admin_roles",
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
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "role", name="uq_admin_roles_user_role"),
    )
    op.create_index(op.f("ix_admin_roles_user_id"), "admin_roles", ["user_id"])
    op.create_index(op.f("ix_admin_roles_revoked_at"), "admin_roles", ["revoked_at"])

    op.create_table(
        "admin_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_admin_audit_logs_actor_user_id"), "admin_audit_logs", ["actor_user_id"])
    op.create_index(op.f("ix_admin_audit_logs_action"), "admin_audit_logs", ["action"])
    op.create_index(op.f("ix_admin_audit_logs_target_type"), "admin_audit_logs", ["target_type"])
    op.create_index(op.f("ix_admin_audit_logs_target_id"), "admin_audit_logs", ["target_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_audit_logs_target_id"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_target_type"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_action"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_actor_user_id"), table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")

    op.drop_index(op.f("ix_admin_roles_revoked_at"), table_name="admin_roles")
    op.drop_index(op.f("ix_admin_roles_user_id"), table_name="admin_roles")
    op.drop_table("admin_roles")

    op.drop_index(op.f("ix_billing_promo_codes_archived_at"), table_name="billing_promo_codes")
    op.drop_column("billing_promo_codes", "archived_at")

    op.drop_constraint(
        "fk_users_account_status_changed_by_user_id_users", "users", type_="foreignkey"
    )
    op.drop_index(op.f("ix_users_account_status"), table_name="users")
    op.drop_column("users", "account_status_changed_by_user_id")
    op.drop_column("users", "account_status_changed_at")
    op.drop_column("users", "account_status_reason")
    op.drop_column("users", "account_status")
