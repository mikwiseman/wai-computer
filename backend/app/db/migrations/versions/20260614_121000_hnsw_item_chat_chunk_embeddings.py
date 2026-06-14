"""Add HNSW indexes for item and chat chunk embeddings.

Revision ID: 20260614_121000
Revises: 20260614_120000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260614_121000"
down_revision: Union[str, tuple[str, str], None] = "20260614_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = (
    ("idx_item_chunks_embedding_hnsw", "item_chunks"),
    ("idx_conversation_chunks_embedding_hnsw", "conversation_chunks"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name in _INDEXES:
            op.execute(
                f"""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name}
                ON {table_name}
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
                WHERE embedding IS NOT NULL
                """
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, _table_name in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
