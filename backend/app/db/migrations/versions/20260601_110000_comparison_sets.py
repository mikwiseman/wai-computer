"""comparison_sets (multi-item comparison tables)

Revision ID: 20260601_110000
Revises: 20260601_100000
Create Date: 2026-06-01 11:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260601_110000"
down_revision: Union[str, None] = "20260601_100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comparison_sets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("item_ids", postgresql.JSONB(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=True),
        sa.Column("rows", postgresql.JSONB(), nullable=True),
        sa.Column("schema_rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
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
    )
    op.create_index("ix_comparison_sets_user_id", "comparison_sets", ["user_id"])
    op.create_index(
        "ix_comparison_sets_user_created", "comparison_sets", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_comparison_sets_user_created", table_name="comparison_sets")
    op.drop_index("ix_comparison_sets_user_id", table_name="comparison_sets")
    op.drop_table("comparison_sets")
