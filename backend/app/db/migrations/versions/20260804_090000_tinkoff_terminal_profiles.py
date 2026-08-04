"""Bind T-Bank subscriptions to the terminal that issued their RebillId.

Revision ID: 20260804_090000
Revises: 20260721_120000
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_090000"
down_revision: Union[str, None] = "20260721_120000"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "billing_subscriptions",
        sa.Column("tinkoff_terminal_profile", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE billing_subscriptions
        SET tinkoff_terminal_profile = 'legacy'
        WHERE provider = 'tinkoff'
        """
    )
    op.create_check_constraint(
        "ck_billing_subscriptions_tinkoff_terminal_profile",
        "billing_subscriptions",
        "tinkoff_terminal_profile IS NULL OR tinkoff_terminal_profile IN ('legacy', 'wai_computer')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_billing_subscriptions_tinkoff_terminal_profile",
        "billing_subscriptions",
        type_="check",
    )
    op.drop_column("billing_subscriptions", "tinkoff_terminal_profile")
