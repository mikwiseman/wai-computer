"""add telegram_media_group_parts album buffer

Telegram albums arrive as N independent webhook updates sharing a
media_group_id. The API runs multiple gunicorn workers, so the parts are
buffered in this table and a debounced Celery task processes the album as one
capture (one combined vision pass, one material, one reply).

Revision ID: 20260713_090000
Revises: 20260709_120000
Create Date: 2026-07-13 09:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260713_090000"
down_revision: Union[str, tuple[str, str], None] = "20260709_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_media_group_parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("media_group_id", sa.String(length=64), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("message", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("media_group_id", "message_id", name="uq_tg_media_group_part"),
    )
    op.create_index(
        "ix_telegram_media_group_parts_media_group_id",
        "telegram_media_group_parts",
        ["media_group_id"],
    )
    op.create_index(
        "ix_telegram_media_group_parts_telegram_user_id",
        "telegram_media_group_parts",
        ["telegram_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_media_group_parts_telegram_user_id",
        table_name="telegram_media_group_parts",
    )
    op.drop_index(
        "ix_telegram_media_group_parts_media_group_id",
        table_name="telegram_media_group_parts",
    )
    op.drop_table("telegram_media_group_parts")
