"""Add provider payment uniqueness for billing invoices.

Revision ID: 20260614_123000
Revises: 20260614_122000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260614_123000"
down_revision: Union[str, tuple[str, str], None] = "20260614_122000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
            uq_billing_invoices_provider_payment_id
            ON billing_invoices (provider_payment_id)
            WHERE provider_payment_id IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS uq_billing_invoices_provider_payment_id"
        )
