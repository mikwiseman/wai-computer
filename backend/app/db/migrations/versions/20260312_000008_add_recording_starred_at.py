"""Add starred_at column to recordings table.

Revision ID: 000008
Revises: 000007
Create Date: 2026-03-12
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000008"
down_revision: Union[str, None] = "000007"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("starred_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recordings", "starred_at")
