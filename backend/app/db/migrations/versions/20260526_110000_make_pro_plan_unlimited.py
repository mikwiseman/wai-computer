"""make pro plan unlimited

Revision ID: 20260526_110000
Revises: 20260526_100000
Create Date: 2026-05-26 11:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260526_110000"
down_revision: Union[str, None] = "20260526_100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE billing_plans
            SET description = 'Unlimited transcription, permanent memory, agents, MCP, advanced search.',
                word_cap_per_week = NULL
            WHERE code = 'pro'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE billing_plans
            SET description = '50,000 transcribed words per week, permanent memory, agents, MCP, advanced search.',
                word_cap_per_week = 50000
            WHERE code = 'pro'
            """
        )
    )
