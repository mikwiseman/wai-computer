"""add stripe_customer_id to users

Revision ID: 20260527_150000
Revises: 20260527_120000
Create Date: 2026-05-27 15:00:00.000000+00:00

Lifts ``stripe_customer_id`` from ``billing_subscriptions`` up to ``users`` so
the Customer Portal can be opened (and ``stripe.Invoice.list`` called) without
requiring an active subscription. Set lazily by ``POST /api/billing/portal``
the first time a user clicks Manage subscription.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_150000"
down_revision: Union[str, None] = "20260527_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sa.String(length=120), nullable=True),
    )
    # Back-fill from the most recent billing_subscriptions row so existing
    # paying users skip the lazy-create path on their next portal click.
    op.execute(
        """
        UPDATE users u
        SET stripe_customer_id = bs.stripe_customer_id
        FROM (
            SELECT DISTINCT ON (user_id) user_id, stripe_customer_id
            FROM billing_subscriptions
            WHERE stripe_customer_id IS NOT NULL
            ORDER BY user_id, updated_at DESC
        ) bs
        WHERE bs.user_id = u.id
          AND u.stripe_customer_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("users", "stripe_customer_id")
