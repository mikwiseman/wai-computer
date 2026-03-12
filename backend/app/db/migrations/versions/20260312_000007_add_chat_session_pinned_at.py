"""add pinned_at to chat_sessions

Revision ID: 000007
Revises: dc79b7dd96c1
Create Date: 2026-03-12 04:00:00.000000+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "000007"
down_revision: Union[str, None] = "dc79b7dd96c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "pinned_at")
