"""create user reminders

Revision ID: 20260604_130000
Revises: 20260604_121000
Create Date: 2026-06-04 13:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260604_130000"
down_revision = "20260604_121000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_reminders",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=30), server_default="telegram", nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_reminders_user_id"), "user_reminders", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_reminders_status"), "user_reminders", ["status"], unique=False)
    op.create_index(
        "ix_user_reminders_status_due_at",
        "user_reminders",
        ["status", "due_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_reminders_status_due_at", table_name="user_reminders")
    op.drop_index(op.f("ix_user_reminders_status"), table_name="user_reminders")
    op.drop_index(op.f("ix_user_reminders_user_id"), table_name="user_reminders")
    op.drop_table("user_reminders")
