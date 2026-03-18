"""Add unique constraints on folder and tag names per user — REVERTED

This migration was reverted because it caused production deploy failures.
The upgrade() is now a no-op. The constraints are NOT applied.

Revision ID: 000010
Revises: 000009
Create Date: 2026-03-18
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "000010"
down_revision: Union[str, None] = "000009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # REVERTED: unique constraints caused deploy failures.
    # This migration is intentionally a no-op.
    pass


def downgrade() -> None:
    # Nothing to undo since upgrade is a no-op.
    pass
