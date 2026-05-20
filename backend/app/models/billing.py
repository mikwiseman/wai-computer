"""Billing models: plans, subscriptions, invoices, events, usage tracking."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class PlanCode(str, enum.Enum):
    """Canonical plan codes."""

    FREE = "free"
    PRO = "pro"


class BillingProvider(str, enum.Enum):
    """Payment provider rails."""

    STRIPE = "stripe"
    TINKOFF = "tinkoff"


class SubscriptionStatus(str, enum.Enum):
    """Subscription lifecycle states (normalized across providers)."""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    EXPIRED = "expired"


class BillingPeriod(str, enum.Enum):
    """Billing cadence."""

    MONTH = "month"
    YEAR = "year"


class Plan(Base, UUIDMixin, TimestampMixin):
    """Billing plan with feature flags and per-rail price references."""

    __tablename__ = "billing_plans"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stripe price IDs (set per environment via seed or admin update)
    stripe_price_id_monthly: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_price_id_yearly: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # T-Bank charges raw RUB amounts (no Price object on their side)
    tinkoff_amount_rub_monthly: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    tinkoff_amount_rub_yearly: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # USD price hints for marketing display (source of truth is Stripe Price)
    usd_amount_monthly: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    usd_amount_yearly: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Quota & entitlement caps. NULL means the plan does not expose a weekly cap.
    word_cap_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Feature flag bag (agents, mcp, advanced_search, etc.)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="plan"
    )


class Subscription(Base, UUIDMixin, TimestampMixin):
    """User subscription — single source of truth across Stripe + T-Bank rails."""

    __tablename__ = "billing_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_plans.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SubscriptionStatus.ACTIVE.value,
        server_default=SubscriptionStatus.ACTIVE.value,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(10), nullable=False)

    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Stripe sidecar
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # T-Bank sidecar — Recurrent flow uses CustomerKey + RebillId.
    tinkoff_customer_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tinkoff_rebill_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    tinkoff_next_charge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    plan: Mapped["Plan"] = relationship("Plan", back_populates="subscriptions")
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="subscription", cascade="all, delete-orphan"
    )
    events: Mapped[list["BillingEvent"]] = relationship(
        "BillingEvent", back_populates="subscription", cascade="all, delete-orphan"
    )


class Invoice(Base, UUIDMixin, TimestampMixin):
    """Successful or failed payment record."""

    __tablename__ = "billing_invoices"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="invoices")


class BillingEvent(Base, UUIDMixin, TimestampMixin):
    """Normalized event log from both rails — append-only audit trail."""

    __tablename__ = "billing_events"

    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    subscription: Mapped["Subscription | None"] = relationship(
        "Subscription", back_populates="events"
    )


class UsageWeek(Base, UUIDMixin):
    """Weekly transcribed-words counter for free-tier quota enforcement.

    week_start_utc is the Sunday 00:00 UTC anchoring the week, matching Whispr's
    reset cadence. UPSERT keyed by (user_id, week_start_utc).
    """

    __tablename__ = "billing_usage_weeks"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start_utc", name="uq_billing_usage_user_week"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start_utc: Mapped[date] = mapped_column(Date, nullable=False)
    words_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        onupdate=datetime.utcnow,
    )
