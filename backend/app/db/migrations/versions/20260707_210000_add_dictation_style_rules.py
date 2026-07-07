"""add dictation style rules to users

Revision ID: 20260707_210000
Revises: 20260615_120000
Create Date: 2026-07-07 21:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260707_210000"
down_revision: Union[str, tuple[str, str], None] = "20260615_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("dictation_style_rules", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "dictation_style_rules")
