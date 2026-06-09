"""Add entities.dossier_dirty for the O(changed) living-wiki recompile (P3)

A new mention/relation flips dossier_dirty=true; a bounded, cache-aware sweep
refreshes only the changed dossiers (unchanged fingerprints cost no LLM). Partial
index so the sweep scans only dirty rows.

Revision ID: 20260610_150000
Revises: 20260610_140000
Create Date: 2026-06-10 15:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_150000"
down_revision: Union[str, tuple[str, str], None] = "20260610_140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("dossier_dirty", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "entities",
        sa.Column("dossier_dirty_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_entities_dossier_dirty",
        "entities",
        ["dossier_dirty"],
        postgresql_where=sa.text("dossier_dirty"),
    )


def downgrade() -> None:
    op.drop_index("ix_entities_dossier_dirty", table_name="entities")
    op.drop_column("entities", "dossier_dirty_at")
    op.drop_column("entities", "dossier_dirty")
