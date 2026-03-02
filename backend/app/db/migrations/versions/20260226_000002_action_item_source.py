"""Add source column to action_items

Revision ID: 000002
Revises: 000001
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "000002"
down_revision: Union[str, None] = "000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "action_items",
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default="generated",
        ),
    )
    op.alter_column("action_items", "source", server_default=None)


def downgrade() -> None:
    op.drop_column("action_items", "source")
