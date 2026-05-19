"""seed Stripe price ids for the Pro billing plan

Revision ID: 20260520_190000
Revises: 20260520_180000
Create Date: 2026-05-20 19:00:00.000000+00:00

"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_190000"
down_revision: Union[str, None] = "20260520_180000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STRIPE_PRO_MONTHLY_PRICE_ID = "price_1TYUaVENNsR4WtAWrMI4kLWf"
STRIPE_PRO_YEARLY_PRICE_ID = "price_1TYUaWENNsR4WtAWRuIYlp7t"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE billing_plans
            SET stripe_price_id_monthly = COALESCE(
                    stripe_price_id_monthly,
                    :monthly_price_id
                ),
                stripe_price_id_yearly = COALESCE(
                    stripe_price_id_yearly,
                    :yearly_price_id
                )
            WHERE code = 'pro'
            """
        ).bindparams(
            monthly_price_id=STRIPE_PRO_MONTHLY_PRICE_ID,
            yearly_price_id=STRIPE_PRO_YEARLY_PRICE_ID,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE billing_plans
            SET stripe_price_id_monthly = NULL,
                stripe_price_id_yearly = NULL
            WHERE code = 'pro'
              AND stripe_price_id_monthly = :monthly_price_id
              AND stripe_price_id_yearly = :yearly_price_id
            """
        ).bindparams(
            monthly_price_id=STRIPE_PRO_MONTHLY_PRICE_ID,
            yearly_price_id=STRIPE_PRO_YEARLY_PRICE_ID,
        )
    )
