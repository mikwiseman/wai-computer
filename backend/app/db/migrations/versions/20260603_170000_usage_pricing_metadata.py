"""add usage pricing metadata

Revision ID: 20260603_170000
Revises: 20260603_160000
Create Date: 2026-06-03 17:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_170000"
down_revision: Union[str, None] = "20260603_160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_usage_events", sa.Column("billing_mode", sa.String(length=32)))
    op.add_column("ai_usage_events", sa.Column("language_mode", sa.String(length=32)))
    op.add_column(
        "ai_usage_events",
        sa.Column("addons", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("ai_usage_events", sa.Column("price_source", sa.String(length=120)))

    op.add_column("deepgram_usage_events", sa.Column("estimated_cost_usd", sa.Float()))
    op.add_column(
        "deepgram_usage_events",
        sa.Column(
            "pricing_status",
            sa.String(length=32),
            server_default="unpriced",
            nullable=False,
        ),
    )
    op.add_column("deepgram_usage_events", sa.Column("billing_mode", sa.String(length=32)))
    op.add_column("deepgram_usage_events", sa.Column("language_mode", sa.String(length=32)))
    op.add_column(
        "deepgram_usage_events",
        sa.Column("addons", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("deepgram_usage_events", sa.Column("price_source", sa.String(length=120)))


def downgrade() -> None:
    op.drop_column("deepgram_usage_events", "price_source")
    op.drop_column("deepgram_usage_events", "addons")
    op.drop_column("deepgram_usage_events", "language_mode")
    op.drop_column("deepgram_usage_events", "billing_mode")
    op.drop_column("deepgram_usage_events", "pricing_status")
    op.drop_column("deepgram_usage_events", "estimated_cost_usd")

    op.drop_column("ai_usage_events", "price_source")
    op.drop_column("ai_usage_events", "addons")
    op.drop_column("ai_usage_events", "language_mode")
    op.drop_column("ai_usage_events", "billing_mode")
