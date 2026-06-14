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

DROP_PROVIDER_PAYMENT_UNIQUE_INDEX_SQL = (
    "DROP INDEX CONCURRENTLY IF EXISTS uq_billing_invoices_provider_payment_id"
)

REJECT_CONFLICTING_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM billing_invoices
        WHERE provider_payment_id IS NOT NULL
        GROUP BY provider_payment_id
        HAVING COUNT(*) > 1
           AND COUNT(
               DISTINCT (
                   subscription_id,
                   amount,
                   currency,
                   status,
                   COALESCE(receipt_url, '')
               )
           ) > 1
    ) THEN
        RAISE EXCEPTION
            'Conflicting duplicate billing invoice provider_payment_id values exist';
    END IF;
END $$;
"""

DELETE_SEMANTIC_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL = """
WITH duplicate_groups AS (
    SELECT provider_payment_id
    FROM billing_invoices
    WHERE provider_payment_id IS NOT NULL
    GROUP BY provider_payment_id
    HAVING COUNT(*) > 1
       AND COUNT(
           DISTINCT (
               subscription_id,
               amount,
               currency,
               status,
               COALESCE(receipt_url, '')
           )
       ) = 1
),
ranked_duplicates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY provider_payment_id
            ORDER BY created_at ASC, id ASC
        ) AS duplicate_rank
    FROM billing_invoices
    WHERE provider_payment_id IN (
        SELECT provider_payment_id
        FROM duplicate_groups
    )
)
DELETE FROM billing_invoices AS invoice
USING ranked_duplicates
WHERE invoice.id = ranked_duplicates.id
  AND ranked_duplicates.duplicate_rank > 1;
"""

CREATE_PROVIDER_PAYMENT_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX CONCURRENTLY uq_billing_invoices_provider_payment_id
ON billing_invoices (provider_payment_id)
WHERE provider_payment_id IS NOT NULL
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(DROP_PROVIDER_PAYMENT_UNIQUE_INDEX_SQL)

    op.execute(REJECT_CONFLICTING_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL)
    op.execute(DELETE_SEMANTIC_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL)

    with op.get_context().autocommit_block():
        op.execute(CREATE_PROVIDER_PAYMENT_UNIQUE_INDEX_SQL)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(DROP_PROVIDER_PAYMENT_UNIQUE_INDEX_SQL)
