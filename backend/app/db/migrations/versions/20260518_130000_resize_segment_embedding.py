"""resize segments.embedding to 3072 for text-embedding-3-large

Revision ID: 20260518_130000
Revises: 20260518_120000
Create Date: 2026-05-18 13:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260518_130000"
down_revision: Union[str, None] = "20260518_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old 384-dim embeddings (sentence-transformers all-MiniLM-L6-v2) cannot be
    # cast to 3072. Drop and recreate; backfill via scripts/reembed-segments.py
    # after the deploy completes.
    op.drop_column("segments", "embedding")
    op.add_column(
        "segments",
        sa.Column("embedding", Vector(3072), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("segments", "embedding")
    op.add_column(
        "segments",
        sa.Column("embedding", Vector(384), nullable=True),
    )
