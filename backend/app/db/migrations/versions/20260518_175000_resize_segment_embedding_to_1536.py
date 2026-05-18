"""resize segments.embedding to 1536 for indexed OpenAI embeddings

Revision ID: 20260518_175000
Revises: 20260518_170000
Create Date: 2026-05-18 18:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260518_175000"
down_revision: Union[str, None] = "20260518_170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # text-embedding-3-large defaults to 3072 dimensions, but pgvector ivfflat
    # indexes support vectors up to 2000 dimensions. Store the requested 1536-d
    # embeddings so semantic search remains indexed.
    op.execute("DROP INDEX IF EXISTS idx_segments_embedding")
    op.drop_column("segments", "embedding")
    op.add_column("segments", sa.Column("embedding", Vector(1536), nullable=True))
    op.create_index(
        "idx_segments_embedding",
        "segments",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_segments_embedding")
    op.drop_column("segments", "embedding")
    op.add_column("segments", sa.Column("embedding", Vector(3072), nullable=True))
