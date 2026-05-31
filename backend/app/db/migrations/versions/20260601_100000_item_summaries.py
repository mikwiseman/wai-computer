"""item_summaries (AI summary + key-moments table for Items)

Stores the structured summary and the hero key-moments table for an Item as
JSONB, one row per item. Keeps the recordings-only summaries/action_items/
highlights tables untouched (zero regression surface).

Revision ID: 20260601_100000
Revises: 20260601_090000
Create Date: 2026-06-01 10:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260601_100000"
down_revision: Union[str, None] = "20260601_090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_summaries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_points", postgresql.JSONB(), nullable=True),
        sa.Column("decisions", postgresql.JSONB(), nullable=True),
        sa.Column("action_items", postgresql.JSONB(), nullable=True),
        sa.Column("topics", postgresql.JSONB(), nullable=True),
        sa.Column("people_mentioned", postgresql.JSONB(), nullable=True),
        sa.Column("highlights", postgresql.JSONB(), nullable=True),
        sa.Column("key_moments", postgresql.JSONB(), nullable=True),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("item_id", name="uq_item_summaries_item"),
    )
    op.create_index("ix_item_summaries_item_id", "item_summaries", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_item_summaries_item_id", table_name="item_summaries")
    op.drop_table("item_summaries")
