"""GIN full-text index on item_chunks.content (Russian stemmer + ICU folding)

Unified search (``app/core/unified_search.py``) full-text-matches item chunks with
``to_tsvector('russian', lower(ic.content COLLATE "und-x-icu"))`` but no matching
index exists, so every item-chunk FTS query sequentially scans the whole table.
Add the expression GIN index — identical to the one segments already have
(``idx_segments_content_fts``) — so item full-text search uses an index. Pure
performance; no schema/data change.

Revision ID: 20260601_140000
Revises: 20260601_130000
Create Date: 2026-06-01 14:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

from alembic import op

revision: str = "20260601_140000"
down_revision: Union[str, None] = "20260601_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Must match the query expression in unified_search.py EXACTLY (same
    # 'russian' config + lower(... COLLATE "und-x-icu")) or the planner won't
    # use the index. The DB ctype may be `C`, which can't case-fold Cyrillic,
    # so the ICU collation does the lowercasing on both index and query sides.
    op.execute(
        """CREATE INDEX IF NOT EXISTS idx_item_chunks_content_fts ON item_chunks """
        """USING gin (to_tsvector('russian', lower(content COLLATE "und-x-icu")))"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_item_chunks_content_fts")
