"""create billing tables and add billing columns to users

Revision ID: 20260520_120000
Revises: 20260519_120000
Create Date: 2026-05-20 12:00:00.000000+00:00

Adds the billing layer:

- ``billing_plans``: catalog of subscription plans (free, pro) with per-rail
  price references, weekly word caps, and memory retention windows.
- ``billing_subscriptions``: per-user active subscription. Provider-agnostic
  with Stripe (``stripe_subscription_id``) and T-Bank (``tinkoff_rebill_id``)
  sidecar columns.
- ``billing_invoices``: per-charge audit + receipt URL.
- ``billing_events``: append-only normalized event log.
- ``billing_usage_weeks``: weekly transcribed-words counter, anchored to
  Sunday 00:00 UTC for free-tier quota enforcement.
- ``users.region``: ``global|ru`` — seeded from WAIDownloadRegion at signup.
- ``users.current_subscription_id``: convenience pointer to the active row.

Also seeds the ``free`` and ``pro`` plans inline so a fresh deployment is
immediately functional.
"""

from typing import Sequence, Union  # noqa: F401

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260520_120000"
down_revision: Union[str, None] = "20260519_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- billing_plans -----------------------------------------------------
    op.create_table(
        "billing_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(20), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("stripe_price_id_monthly", sa.String(120), nullable=True),
        sa.Column("stripe_price_id_yearly", sa.String(120), nullable=True),
        sa.Column("tinkoff_amount_rub_monthly", sa.Numeric(12, 2), nullable=True),
        sa.Column("tinkoff_amount_rub_yearly", sa.Numeric(12, 2), nullable=True),
        sa.Column("usd_amount_monthly", sa.Numeric(12, 2), nullable=True),
        sa.Column("usd_amount_yearly", sa.Numeric(12, 2), nullable=True),
        sa.Column("word_cap_per_week", sa.Integer, nullable=True),
        sa.Column("memory_retention_days", sa.Integer, nullable=True),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
    )

    # --- billing_subscriptions --------------------------------------------
    op.create_table(
        "billing_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("billing_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("billing_period", sa.String(10), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(120), nullable=True, unique=True),
        sa.Column("stripe_customer_id", sa.String(120), nullable=True),
        sa.Column("tinkoff_customer_key", sa.String(120), nullable=True),
        sa.Column("tinkoff_rebill_id", sa.String(120), nullable=True, unique=True),
        sa.Column(
            "tinkoff_next_charge_at", sa.DateTime(timezone=True), nullable=True, index=True
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
    )

    # --- billing_invoices --------------------------------------------------
    op.create_table(
        "billing_invoices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_payment_id", sa.String(120), nullable=True, index=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_url", sa.String(500), nullable=True),
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
    )

    # --- billing_events ----------------------------------------------------
    op.create_table(
        "billing_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("type", sa.String(60), nullable=False, index=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
    )

    # --- billing_usage_weeks ----------------------------------------------
    op.create_table(
        "billing_usage_weeks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("week_start_utc", sa.Date, nullable=False),
        sa.Column("words_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "week_start_utc", name="uq_billing_usage_user_week"),
    )

    # --- users additions ---------------------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "region", sa.String(10), nullable=False, server_default="global"
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "current_subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "billing_subscriptions.id", ondelete="SET NULL", use_alter=True,
                name="fk_users_current_subscription",
            ),
            nullable=True,
        ),
    )

    # --- seed default plans ------------------------------------------------
    op.execute(
        """
        INSERT INTO billing_plans (
            code, name, description,
            usd_amount_monthly, usd_amount_yearly,
            tinkoff_amount_rub_monthly, tinkoff_amount_rub_yearly,
            word_cap_per_week, memory_retention_days, features
        ) VALUES (
            'free',
            'Free',
            '10,000 transcribed words per week, 30-day memory window.',
            0, 0, 0, 0,
            10000, 30,
            '{"agents": false, "mcp": false, "advanced_search": false}'::jsonb
        ),
        (
            'pro',
            'Pro',
            'Unlimited transcription, permanent memory, agents, MCP, advanced search.',
            12, 96, 999, 7999,
            NULL, NULL,
            '{"agents": true, "mcp": true, "advanced_search": true}'::jsonb
        );
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_current_subscription", "users", type_="foreignkey")
    op.drop_column("users", "current_subscription_id")
    op.drop_column("users", "region")
    op.drop_table("billing_usage_weeks")
    op.drop_table("billing_events")
    op.drop_table("billing_invoices")
    op.drop_table("billing_subscriptions")
    op.drop_table("billing_plans")
