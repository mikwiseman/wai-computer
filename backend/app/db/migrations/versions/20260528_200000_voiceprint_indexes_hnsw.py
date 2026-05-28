"""voiceprint vector indexes -> HNSW

Revision ID: 20260528_200000
Revises: 20260528_170000
Create Date: 2026-05-28 20:00:00.000000+00:00

Replaces the IVFFlat indexes on the three voice vector tables with HNSW.
At our scale (<<100k rows per table) IVFFlat with lists=100 was strictly
worse than a sequential scan because the centroids were built on a near-
empty table and every probe ran through ~all lists anyway. HNSW (m=16,
ef_construction=64) gives good recall from row 1 and scales smoothly
into the hundreds-of-thousands range that the public directory may hit.

The migration drops and re-creates concurrently where possible (the
voiceprints + recording_speaker_embeddings tables are small enough that
non-concurrent is fine; the public_voiceprints table is also young).
"""

from typing import Sequence, Union  # noqa: F401

from alembic import op

revision: str = "20260528_200000"
down_revision: Union[str, None] = "20260528_170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    ("voiceprints", "ix_voiceprints_embedding", True),
    ("recording_speaker_embeddings", "ix_recording_speaker_embeddings_embedding", False),
    ("public_voiceprints", "ix_public_voiceprints_embedding", True),
]


def upgrade() -> None:
    for table, index_name, _had_ivfflat in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        op.execute(
            f"CREATE INDEX {index_name} ON {table} "
            f"USING hnsw (embedding vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64)"
        )
        op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    for table, index_name, had_ivfflat in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        if not had_ivfflat:
            continue
        op.execute(
            f"CREATE INDEX {index_name} ON {table} "
            f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
