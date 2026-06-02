"""comparison_sets.intent — persist the user's comparison framing

The intent ("by price", "which is healthier") was passed to the build task but
never stored, so a rebuild couldn't re-use it. Add a nullable column.

Revision ID: 20260602_110000
Revises: 20260602_100000
Create Date: 2026-06-02 11:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_110000"
down_revision: Union[str, None] = "20260602_100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_sets", sa.Column("intent", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("comparison_sets", "intent")
