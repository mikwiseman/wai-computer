"""add display_name to users for greeting + voice-enrollment seed

Revision ID: 20260519_130000
Revises: 20260519_120000
Create Date: 2026-05-19 13:00:00.000000+00:00
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260519_130000"
down_revision: Union[str, None] = "20260519_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
