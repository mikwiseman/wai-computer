"""Add authority_score + salience_score to recordings and conversations

Parity columns so the trust-weighted ranking (P4) can apply ONE clamped
authority×salience multiplier across all three source kinds (items already have
them). Defaults are neutral (0.5 -> ×1.0 multiplier) so enabling the ranking flag
changes nothing until real signal is populated.

Revision ID: 20260610_140000
Revises: 20260610_130000
Create Date: 2026-06-10 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260610_140000"
down_revision: Union[str, tuple[str, str], None] = "20260610_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("recordings", "conversations"):
        op.add_column(
            table,
            sa.Column("authority_score", sa.Float(), server_default="0.5", nullable=False),
        )
        op.add_column(table, sa.Column("salience_score", sa.Float(), nullable=True))


def downgrade() -> None:
    for table in ("recordings", "conversations"):
        op.drop_column(table, "salience_score")
        op.drop_column(table, "authority_score")
