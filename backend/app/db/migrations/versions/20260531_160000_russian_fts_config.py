"""switch segment full-text search to the Russian stemmer

Issue 104: search must match Russian word forms (рижский → рижская/рижские/...).
The segment FTS index was built with the 'english' configuration, which does not
stem Russian. Recreate it with the 'russian' Snowball configuration so the
``/search`` and ``/search/fts`` endpoints (and qa.py retrieval) match inflected
forms. Recreating the GIN index reindexes every existing segment.

Revision ID: 20260531_160000
Revises: 20260531_140000
Create Date: 2026-05-31 16:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

from alembic import op

revision: str = "20260531_160000"
down_revision: Union[str, None] = "20260531_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fold case via ICU (`und-x-icu`) rather than the libc collation: the
    # database ctype may be `C`, which does not lowercase Cyrillic, so plain
    # `to_tsvector('russian', content)` would leave sentence-initial / proper-noun
    # forms uppercased and unmatched. The query path applies the identical
    # `lower(... COLLATE "und-x-icu")` so this expression index stays usable.
    op.execute("DROP INDEX IF EXISTS idx_segments_content_fts")
    op.execute(
        """CREATE INDEX idx_segments_content_fts ON segments """
        """USING gin (to_tsvector('russian', lower(content COLLATE "und-x-icu")))"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_segments_content_fts")
    op.execute(
        """CREATE INDEX idx_segments_content_fts ON segments """
        """USING gin (to_tsvector('english', content))"""
    )
