"""add T-Bank order id to subscriptions

Revision ID: 20260522_120000
Revises: 20260522_110000
Create Date: 2026-05-22 12:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_120000"
down_revision: Union[str, None] = "20260522_110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "billing_subscriptions",
        sa.Column("tinkoff_order_id", sa.String(length=120), nullable=True),
    )
    op.create_unique_constraint(
        "uq_billing_subscriptions_tinkoff_order_id",
        "billing_subscriptions",
        ["tinkoff_order_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_billing_subscriptions_tinkoff_order_id",
        "billing_subscriptions",
        type_="unique",
    )
    op.drop_column("billing_subscriptions", "tinkoff_order_id")
