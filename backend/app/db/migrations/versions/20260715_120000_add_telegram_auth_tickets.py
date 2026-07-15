"""add split-secret Telegram auth tickets

Revision ID: 20260715_120000
Revises: 20260714_130000
Create Date: 2026-07-15 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260715_120000"
down_revision: Union[str, tuple[str, str], None] = "20260714_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_auth_tickets",
        sa.Column("start_token_hash", sa.String(length=64), nullable=False),
        sa.Column("poll_token_hash", sa.String(length=64), nullable=False),
        sa.Column("client", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exchanged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_token_hash"),
        sa.UniqueConstraint("start_token_hash"),
    )
    op.create_index(
        op.f("ix_telegram_auth_tickets_poll_token_hash"),
        "telegram_auth_tickets",
        ["poll_token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_auth_tickets_start_token_hash"),
        "telegram_auth_tickets",
        ["start_token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_auth_tickets_telegram_user_id"),
        "telegram_auth_tickets",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_auth_tickets_user_id"),
        "telegram_auth_tickets",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_telegram_auth_tickets_user_id"),
        table_name="telegram_auth_tickets",
    )
    op.drop_index(
        op.f("ix_telegram_auth_tickets_telegram_user_id"),
        table_name="telegram_auth_tickets",
    )
    op.drop_index(
        op.f("ix_telegram_auth_tickets_start_token_hash"),
        table_name="telegram_auth_tickets",
    )
    op.drop_index(
        op.f("ix_telegram_auth_tickets_poll_token_hash"),
        table_name="telegram_auth_tickets",
    )
    op.drop_table("telegram_auth_tickets")
