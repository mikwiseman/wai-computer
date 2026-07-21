"""add automatic recording title preference

Revision ID: 20260721_120000
Revises: 20260720_120000
Create Date: 2026-07-21 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_120000"
down_revision: Union[str, None] = "20260720_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "automatic_recording_titles",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # The old default treated every title as AI-owned, including file names.
    # Freeze existing titles; new live recordings opt in explicitly through
    # title_mode="automatic".
    op.execute(sa.text("UPDATE recordings SET title_auto_generated = false"))
    op.alter_column(
        "recordings",
        "title_auto_generated",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "recordings",
        "title_auto_generated",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )
    op.drop_column("users", "automatic_recording_titles")
