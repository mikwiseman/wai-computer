"""update billing plan caps and remove launch trial

Revision ID: 20260520_210000
Revises: 20260520_200000
Create Date: 2026-05-20 21:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_210000"
down_revision: Union[str, None] = "20260520_200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE billing_plans
            SET description = '3,000 transcribed words per week, 30-day memory window.',
                word_cap_per_week = 3000
            WHERE code = 'free'
            """
        )
    )
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
    op.execute(
        sa.text(
            """
            UPDATE billing_subscriptions
            SET trial_end = NULL
            WHERE trial_end IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE billing_plans
            SET description = '10,000 transcribed words per week, 30-day memory window.',
                word_cap_per_week = 10000
            WHERE code = 'free'
            """
        )
    )
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
