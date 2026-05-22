"""add promo codes and legal acceptance

Revision ID: 20260522_130000
Revises: 20260522_120000
Create Date: 2026-05-22 13:00:00.000000
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260522_130000"
down_revision: Union[str, None] = "20260522_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("legal_terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("legal_terms_version", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("legal_privacy_version", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("legal_acceptance_locale", sa.String(length=10), nullable=True))
    op.add_column("users", sa.Column("legal_acceptance_source", sa.String(length=20), nullable=True))

    op.create_table(
        "billing_promo_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("billing_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("billing_period", sa.String(length=10), nullable=False, server_default="month"),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("redeemed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("duration_days > 0", name="ck_billing_promo_codes_duration_positive"),
        sa.CheckConstraint(
            "max_redemptions > 0",
            name="ck_billing_promo_codes_max_redemptions_positive",
        ),
        sa.CheckConstraint(
            "redeemed_count >= 0",
            name="ck_billing_promo_codes_redeemed_non_negative",
        ),
        sa.CheckConstraint(
            "redeemed_count <= max_redemptions",
            name="ck_billing_promo_codes_redeemed_within_max",
        ),
        sa.UniqueConstraint("code_hash", name="uq_billing_promo_codes_code_hash"),
    )
    op.create_index(
        op.f("ix_billing_promo_codes_code_hash"),
        "billing_promo_codes",
        ["code_hash"],
        unique=False,
    )

    op.create_table(
        "billing_promo_redemptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "promo_code_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("billing_promo_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "promo_code_id",
            "user_id",
            name="uq_billing_promo_redemptions_code_user",
        ),
    )
    op.create_index(op.f("ix_billing_promo_redemptions_promo_code_id"), "billing_promo_redemptions", ["promo_code_id"])
    op.create_index(op.f("ix_billing_promo_redemptions_user_id"), "billing_promo_redemptions", ["user_id"])
    op.create_index(op.f("ix_billing_promo_redemptions_subscription_id"), "billing_promo_redemptions", ["subscription_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_billing_promo_redemptions_subscription_id"), table_name="billing_promo_redemptions")
    op.drop_index(op.f("ix_billing_promo_redemptions_user_id"), table_name="billing_promo_redemptions")
    op.drop_index(op.f("ix_billing_promo_redemptions_promo_code_id"), table_name="billing_promo_redemptions")
    op.drop_table("billing_promo_redemptions")
    op.drop_index(op.f("ix_billing_promo_codes_code_hash"), table_name="billing_promo_codes")
    op.drop_table("billing_promo_codes")

    op.drop_column("users", "legal_acceptance_source")
    op.drop_column("users", "legal_acceptance_locale")
    op.drop_column("users", "legal_privacy_version")
    op.drop_column("users", "legal_terms_version")
    op.drop_column("users", "legal_terms_accepted_at")
