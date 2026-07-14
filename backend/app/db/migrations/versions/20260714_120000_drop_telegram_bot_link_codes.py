"""drop telegram_bot_link_codes

The bot-side /link command that minted these one-time codes was removed
together with the rest of the Telegram account-command surface: linking is
web/Mac/iOS Settings -> deep link -> /start only. With nothing writing codes
the claim flow is dead, so the table goes too.

Revision ID: 20260714_120000
Revises: 20260713_090000
Create Date: 2026-07-14 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_120000"
down_revision: Union[str, tuple[str, str], None] = "20260713_090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_telegram_bot_link_codes_user_id"), table_name="telegram_bot_link_codes")
    op.drop_index(op.f("ix_telegram_bot_link_codes_token_hash"), table_name="telegram_bot_link_codes")
    op.drop_index(
        op.f("ix_telegram_bot_link_codes_telegram_user_id"),
        table_name="telegram_bot_link_codes",
    )
    op.drop_table("telegram_bot_link_codes")


def downgrade() -> None:
    op.create_table(
        "telegram_bot_link_codes",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_telegram_bot_link_codes_telegram_user_id"),
        "telegram_bot_link_codes",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_bot_link_codes_token_hash"),
        "telegram_bot_link_codes",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_bot_link_codes_user_id"),
        "telegram_bot_link_codes",
        ["user_id"],
        unique=False,
    )
