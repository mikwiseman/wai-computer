"""Add default_language column to users table

Revision ID: 000004
Revises: 000003
Create Date: 2026-03-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000004"
down_revision: Union[str, None] = "000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("default_language", sa.String(10), server_default="multi", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "default_language")
