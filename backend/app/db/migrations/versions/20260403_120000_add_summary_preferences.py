"""add summary preferences to users

Revision ID: 20260403_120000
Revises: 20260401_203000
Create Date: 2026-04-03 12:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260403_120000"
down_revision: Union[str, None] = "20260401_203000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("summary_language", sa.String(10), server_default="auto", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("summary_style", sa.String(20), server_default="medium", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("summary_instructions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "summary_instructions")
    op.drop_column("users", "summary_style")
    op.drop_column("users", "summary_language")
