"""Remove orphaned recording entity_mentions.

Revision ID: 20260614_120000
Revises: 20260611_130000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260614_120000"
down_revision: Union[str, tuple[str, str], None] = "20260611_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE entities
        SET dossier_dirty = TRUE,
            dossier_dirty_at = now()
        WHERE id IN (
            SELECT DISTINCT em.entity_id
            FROM entity_mentions em
            WHERE em.source_kind = 'recording'
              AND NOT EXISTS (
                  SELECT 1 FROM recordings r WHERE r.id = em.source_id
              )
        )
        """
    )
    op.execute(
        """
        DELETE FROM entity_mentions em
        WHERE em.source_kind = 'recording'
          AND NOT EXISTS (
              SELECT 1 FROM recordings r WHERE r.id = em.source_id
          )
        """
    )


def downgrade() -> None:
    # Deleted orphan provenance rows cannot be reconstructed without the source
    # recording, so this cleanup is intentionally irreversible.
    pass
