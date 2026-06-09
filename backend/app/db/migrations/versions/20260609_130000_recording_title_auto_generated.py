"""Add recordings.title_auto_generated

Track whether a recording's title was auto-generated (a provisional generate_title
excerpt title, or the full-transcript summary title) versus set by the user. The
authoritative summary title overrides an auto title; a manual rename flips this
False so it is never clobbered. Existing rows default True — almost all titles are
auto-generated, and a user can rename to re-assert ownership.

Revision ID: 20260609_130000
Revises: 20260609_120000
Create Date: 2026-06-09 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_130000"
down_revision: Union[str, tuple[str, str], None] = "20260609_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column(
            "title_auto_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recordings", "title_auto_generated")
