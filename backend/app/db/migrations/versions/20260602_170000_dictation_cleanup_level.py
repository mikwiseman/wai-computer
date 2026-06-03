"""add dictation cleanup level

Revision ID: 20260602_170000
Revises: 20260602_150000
Create Date: 2026-06-02 17:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_170000"
down_revision: Union[str, None] = "20260602_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "dictation_cleanup_level",
            sa.String(length=20),
            server_default="none",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE users
        SET dictation_cleanup_level = CASE
            WHEN dictation_post_filter_enabled THEN 'light'
            ELSE 'none'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("users", "dictation_cleanup_level")
