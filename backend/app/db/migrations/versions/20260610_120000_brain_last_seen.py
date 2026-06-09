"""Add users.brain_last_seen_at (Brain feed watermark)

Powers the "Since you last looked · N new" strip on the Cards-That-Think home
(P0b): a single per-user watermark of when the Brain was last opened. Nullable —
a fresh user has seen nothing, so everything reads as new on first open.

Revision ID: 20260610_120000
Revises: 20260609_130000
Create Date: 2026-06-10 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_120000"
down_revision: Union[str, tuple[str, str], None] = "20260609_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("brain_last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "brain_last_seen_at")
