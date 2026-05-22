"""add recording billed word count

Revision ID: 20260522_110000
Revises: 20260522_100000
Create Date: 2026-05-22 11:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_110000"
down_revision: Union[str, None] = "20260522_100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("billed_word_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("recordings", "billed_word_count")
