"""resize entities.embedding to 3072 for text-embedding-3-large

Revision ID: 20260518_170000
Revises: 20260518_160000
Create Date: 2026-05-18 17:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260518_170000"
down_revision: Union[str, None] = "20260518_160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing 384-dim entity vectors are incompatible with the OpenAI
    # text-embedding-3-large default. We have no users yet, so drop stale
    # vectors rather than keeping a lossy conversion path.
    op.drop_index("idx_entities_embedding", table_name="entities")
    op.drop_column("entities", "embedding")
    op.add_column("entities", sa.Column("embedding", Vector(3072), nullable=True))
    op.create_index(
        "idx_entities_embedding",
        "entities",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )


def downgrade() -> None:
    op.drop_index("idx_entities_embedding", table_name="entities")
    op.drop_column("entities", "embedding")
    op.add_column("entities", sa.Column("embedding", Vector(384), nullable=True))
    op.create_index(
        "idx_entities_embedding",
        "entities",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )
