"""disable dictation post-filter by default

Revision ID: 20260520_170000
Revises: 20260520_160000
Create Date: 2026-05-20 17:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_170000"
down_revision: Union[str, None] = "20260520_160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users
            SET dictation_post_filter_enabled = false
            WHERE dictation_post_filter_enabled = true
            """
        )
    )
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "dictation_post_filter_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
        nullable=False,
    )
