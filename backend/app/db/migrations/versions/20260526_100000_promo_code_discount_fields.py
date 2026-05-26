"""add promo code discount fields

Revision ID: 20260526_100000
Revises: 20260525_130000
Create Date: 2026-05-26 10:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260526_100000"
down_revision: Union[str, None] = "20260525_130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("billing_promo_codes", sa.Column("code", sa.String(length=128), nullable=True))
    op.add_column(
        "billing_promo_codes",
        sa.Column("promotion_type", sa.String(length=20), nullable=False, server_default="access"),
    )
    op.add_column("billing_promo_codes", sa.Column("discount_percent", sa.Integer(), nullable=True))
    op.alter_column("billing_promo_codes", "duration_days", nullable=True)
    op.create_check_constraint(
        "ck_billing_promo_codes_promotion_type",
        "billing_promo_codes",
        "promotion_type IN ('access', 'discount')",
    )
    op.create_check_constraint(
        "ck_billing_promo_codes_access_duration_required",
        "billing_promo_codes",
        "promotion_type != 'access' OR duration_days IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_billing_promo_codes_access_discount_forbidden",
        "billing_promo_codes",
        "promotion_type != 'access' OR discount_percent IS NULL",
    )
    op.create_check_constraint(
        "ck_billing_promo_codes_discount_percent",
        "billing_promo_codes",
        "promotion_type != 'discount' OR (discount_percent IS NOT NULL AND discount_percent BETWEEN 1 AND 99)",
    )
    op.create_check_constraint(
        "ck_billing_promo_codes_discount_duration_forbidden",
        "billing_promo_codes",
        "promotion_type != 'discount' OR duration_days IS NULL",
    )

    op.add_column(
        "billing_subscriptions",
        sa.Column("promo_code_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_billing_subscriptions_promo_code_id",
        "billing_subscriptions",
        "billing_promo_codes",
        ["promo_code_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_billing_subscriptions_promo_code_id"),
        "billing_subscriptions",
        ["promo_code_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_billing_subscriptions_promo_code_id"), table_name="billing_subscriptions")
    op.drop_constraint(
        "fk_billing_subscriptions_promo_code_id",
        "billing_subscriptions",
        type_="foreignkey",
    )
    op.drop_column("billing_subscriptions", "promo_code_id")

    op.drop_constraint(
        "ck_billing_promo_codes_discount_duration_forbidden",
        "billing_promo_codes",
        type_="check",
    )
    op.drop_constraint(
        "ck_billing_promo_codes_discount_percent",
        "billing_promo_codes",
        type_="check",
    )
    op.drop_constraint(
        "ck_billing_promo_codes_access_discount_forbidden",
        "billing_promo_codes",
        type_="check",
    )
    op.drop_constraint(
        "ck_billing_promo_codes_access_duration_required",
        "billing_promo_codes",
        type_="check",
    )
    op.drop_constraint(
        "ck_billing_promo_codes_promotion_type",
        "billing_promo_codes",
        type_="check",
    )
    op.alter_column("billing_promo_codes", "duration_days", nullable=False)
    op.drop_column("billing_promo_codes", "discount_percent")
    op.drop_column("billing_promo_codes", "promotion_type")
    op.drop_column("billing_promo_codes", "code")
