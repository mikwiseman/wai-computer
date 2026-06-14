"""Add HNSW index for recording segment embeddings.

Revision ID: 20260614_122000
Revises: 20260614_121000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260614_122000"
down_revision: Union[str, tuple[str, str], None] = "20260614_121000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_segments_embedding_hnsw
            ON segments
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            WHERE embedding IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_segments_embedding_hnsw")
