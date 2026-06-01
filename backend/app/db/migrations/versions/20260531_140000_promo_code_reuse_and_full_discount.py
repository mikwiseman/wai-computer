"""promo code name reuse after archive + allow 100% discount

Replaces the global UNIQUE(code_hash) with a partial unique index scoped to
non-archived codes, so an archived code's name can be recreated while an
active/paused code still reserves its name. Also raises the discount-percent
ceiling from 99 to 100 to allow full-comp discount codes.

Revision ID: 20260531_140000
Revises: 20260531_120000
Create Date: 2026-05-31 14:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op

revision: str = "20260531_140000"
down_revision: Union[str, None] = "20260528_200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bug 10: uniqueness scoped to non-archived codes.
    op.drop_constraint(
        "uq_billing_promo_codes_code_hash", "billing_promo_codes", type_="unique"
    )
    op.create_index(
        "uq_billing_promo_codes_active_code_hash",
        "billing_promo_codes",
        ["code_hash"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    # Bug 14: allow a full 100% discount.
    op.drop_constraint(
        "ck_billing_promo_codes_discount_percent", "billing_promo_codes", type_="check"
    )
    op.create_check_constraint(
        "ck_billing_promo_codes_discount_percent",
        "billing_promo_codes",
        "promotion_type != 'discount' OR (discount_percent IS NOT NULL AND discount_percent BETWEEN 1 AND 100)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_billing_promo_codes_discount_percent", "billing_promo_codes", type_="check"
    )
    op.create_check_constraint(
        "ck_billing_promo_codes_discount_percent",
        "billing_promo_codes",
        "promotion_type != 'discount' OR (discount_percent IS NOT NULL AND discount_percent BETWEEN 1 AND 99)",
    )

    op.drop_index(
        "uq_billing_promo_codes_active_code_hash", table_name="billing_promo_codes"
    )
    # NOTE: restoring a global UNIQUE will fail if duplicate archived hashes exist.
    op.create_unique_constraint(
        "uq_billing_promo_codes_code_hash", "billing_promo_codes", ["code_hash"]
    )
