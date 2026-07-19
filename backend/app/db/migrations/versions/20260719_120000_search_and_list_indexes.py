"""Fix segment FTS index drift, add list-sort indexes, drop dead ivfflat index

Three pure-performance changes for big-data accounts:

1. ``idx_segments_content_fts`` on production predates the ICU-folding rewrite
   (20260531_160000) and is still ``to_tsvector('russian', content)`` — an
   expression no current query uses, so every segment full-text search
   sequentially scans the whole table, recomputing a tsvector per row
   (pg_stat showed 0 index scans). Recreate it with the exact query-side
   expression to self-heal the drift; a no-op semantic change on databases
   that already match.

2. ``recordings`` has only single-column indexes, but the list endpoint
   filters ``(user_id, deleted_at IS NULL)`` ordered by ``created_at DESC``
   and the native-client sync path orders by ``updated_at`` (no index at
   all). Add both composite indexes so dashboard load and incremental sync
   stop sorting the user's full history per request.

3. ``segments`` carries TWO vector indexes (~1 GB each): the legacy ivfflat
   one and the partial HNSW one. Every semantic query filters
   ``embedding IS NOT NULL`` so the partial HNSW index qualifies everywhere,
   with equal-or-better recall at the session settings
   (``hnsw.ef_search = 80`` vs ``ivfflat.probes = 20``). Drop the ivfflat
   index: frees ~1.1 GB and halves vector index maintenance on the hot
   transcription insert path.

Revision ID: 20260719_120000
Revises: 20260715_120000
Create Date: 2026-07-19 12:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

from alembic import op

revision: str = "20260719_120000"
down_revision: Union[str, None] = "20260715_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Self-heal the segments FTS index to the expression every query uses.
    op.execute("DROP INDEX IF EXISTS idx_segments_content_fts")
    op.execute(
        """CREATE INDEX idx_segments_content_fts ON segments """
        """USING gin (to_tsvector('russian', lower(content COLLATE "und-x-icu")))"""
    )

    # 2. List-sort + sync-watermark composite indexes.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_recordings_user_active_created "
        "ON recordings (user_id, deleted_at, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_recordings_user_updated "
        "ON recordings (user_id, updated_at)"
    )

    # 3. Drop the redundant ivfflat vector index; the partial HNSW index
    #    (idx_segments_embedding_hnsw, WHERE embedding IS NOT NULL) serves all
    #    semantic queries.
    op.execute("DROP INDEX IF EXISTS idx_segments_embedding")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_segments_embedding ON segments "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("DROP INDEX IF EXISTS idx_recordings_user_updated")
    op.execute("DROP INDEX IF EXISTS idx_recordings_user_active_created")
    # Keep the healed FTS expression on downgrade: it matches the query path
    # of every release since 20260531_160000.
