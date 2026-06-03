"""enable dictation cleanup by default

Revision ID: 20260603_120000
Revises: 20260602_180000
Create Date: 2026-06-03 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260603_120000"
down_revision: Union[str, None] = "20260602_180000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET dictation_cleanup_level = 'light',
            dictation_post_filter_enabled = true
        WHERE dictation_cleanup_level = 'none'
        """
    )
    op.alter_column(
        "users",
        "dictation_cleanup_level",
        server_default="light",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        server_default=sa.text("true"),
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "dictation_cleanup_level",
        server_default="none",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        server_default=sa.text("false"),
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )
