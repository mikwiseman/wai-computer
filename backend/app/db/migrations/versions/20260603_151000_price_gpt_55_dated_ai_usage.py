"""price dated gpt-5.5 ai usage events

Revision ID: 20260603_151000
Revises: 20260603_150000
Create Date: 2026-06-03 15:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260603_151000"
down_revision: Union[str, None] = "20260603_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE ai_usage_events
            SET
                estimated_cost_usd = round((
                    (greatest(coalesce(input_tokens, 0) - coalesce(cached_tokens, 0), 0) * 5.00 / 1000000.0)
                    + (least(coalesce(cached_tokens, 0), coalesce(input_tokens, 0)) * 0.50 / 1000000.0)
                    + (coalesce(output_tokens, 0) * 30.00 / 1000000.0)
                )::numeric, 8)::double precision,
                pricing_status = 'priced'
            WHERE provider = 'openai'
              AND model = 'gpt-5.5-2026-04-23'
              AND (input_tokens IS NOT NULL OR output_tokens IS NOT NULL)
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE ai_usage_events
            SET estimated_cost_usd = NULL, pricing_status = 'unpriced'
            WHERE provider = 'openai'
              AND model = 'gpt-5.5-2026-04-23'
            """
        )
    )
