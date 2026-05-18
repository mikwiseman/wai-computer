"""Tests for the Stripe rail: webhook event normalization + subscription mutations."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.billing.providers.base import ProviderEvent, ProviderUnavailableError
from app.billing.providers.stripe_provider import StripeProvider
from app.billing.service import apply_stripe_event
from app.models.billing import (
    BillingEvent,
    Invoice,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.models.user import User


async def _seed_plans(db_session) -> tuple[Plan, Plan]:
    free = (await db_session.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if free is None:
        free = Plan(code="free", name="Free", word_cap_per_week=10000, memory_retention_days=30)
        db_session.add(free)
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one_or_none()
    if pro is None:
        pro = Plan(
            code="pro",
            name="Pro",
            stripe_price_id_monthly="price_test_pro_month",
            stripe_price_id_yearly="price_test_pro_year",
        )
        db_session.add(pro)
    await db_session.flush()
    return free, pro


# ----- provider configuration ---------------------------------------------


def test_stripe_provider_raises_when_secret_missing(monkeypatch):
    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.get_settings",
        lambda: type("S", (), {"stripe_secret_key": "", "stripe_webhook_secret": ""})(),
    )
    p = StripeProvider(secret_key="", webhook_secret="")
    with pytest.raises(ProviderUnavailableError):
        p._client_or_raise()


def test_stripe_provider_returns_client_when_configured():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    client = p._client_or_raise()
    assert client is not None


@pytest.mark.asyncio
async def test_parse_webhook_rejects_missing_signature():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    with pytest.raises(ValueError, match="Missing Stripe-Signature"):
        await p.parse_webhook(raw_body=b"{}", headers={})


@pytest.mark.asyncio
async def test_parse_webhook_extracts_subscription_event():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    fake_event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_abc",
                "status": "active",
                "cancel_at_period_end": False,
            }
        },
    }

    async def fake_create_event(*args, **kwargs):
        return fake_event

    # construct_event is sync on StripeClient; patch the client's method.
    with patch.object(p, "_client_or_raise") as m_client:
        m_client.return_value.construct_event.return_value = fake_event
        result = await p.parse_webhook(
            raw_body=b'{"x":1}',
            headers={"stripe-signature": "t=1,v1=fake"},
        )

    assert result.type == "customer.subscription.updated"
    assert result.subscription_id_provider == "sub_123"
    assert result.customer_id_provider == "cus_abc"
    assert result.status == "active"


# ----- service event handlers ---------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_creates_subscription(db_session):
    free, pro = await _seed_plans(db_session)
    user = User(email="checkout@example.test")
    db_session.add(user)
    await db_session.flush()

    event = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider="sub_abc",
        customer_id_provider="cus_xyz",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user.id),
                    "subscription": "sub_abc",
                    "customer": "cus_xyz",
                    "metadata": {"plan_code": "pro", "period": "month"},
                }
            },
        },
    )
    await apply_stripe_event(db_session, event)

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == "sub_abc")
        )
    ).scalar_one()
    assert sub.user_id == user.id
    assert sub.plan_id == pro.id
    assert sub.billing_period == "month"
    assert sub.stripe_customer_id == "cus_xyz"

    await db_session.refresh(user)
    assert user.current_subscription_id == sub.id

    audit = (
        await db_session.execute(
            select(BillingEvent).where(BillingEvent.type == "stripe.checkout.session.completed")
        )
    ).scalar_one_or_none()
    assert audit is not None


@pytest.mark.asyncio
async def test_subscription_updated_writes_state(db_session):
    free, pro = await _seed_plans(db_session)
    user = User(email="upd@example.test")
    db_session.add(user)
    await db_session.flush()

    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status=SubscriptionStatus.INCOMPLETE.value,
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_upd",
    )
    db_session.add(sub)
    await db_session.flush()

    now = int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
    later = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())

    event = ProviderEvent(
        type="customer.subscription.updated",
        subscription_id_provider="sub_upd",
        customer_id_provider="cus_x",
        status="active",
        raw={
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_upd",
                    "status": "active",
                    "cancel_at_period_end": True,
                    "current_period_start": now,
                    "current_period_end": later,
                    "canceled_at": None,
                    "trial_end": None,
                }
            },
        },
    )
    await apply_stripe_event(db_session, event)
    await db_session.refresh(sub)

    assert sub.status == "active"
    assert sub.cancel_at_period_end is True
    assert sub.current_period_start.isoformat() == "2026-05-01T00:00:00+00:00"
    assert sub.current_period_end.isoformat() == "2026-06-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_invoice_paid_creates_invoice_row(db_session):
    free, pro = await _seed_plans(db_session)
    user = User(email="inv@example.test")
    db_session.add(user)
    await db_session.flush()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status=SubscriptionStatus.ACTIVE.value,
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_inv",
    )
    db_session.add(sub)
    await db_session.flush()

    event = ProviderEvent(
        type="invoice.paid",
        subscription_id_provider="sub_inv",
        customer_id_provider="cus_inv",
        status=None,
        raw={
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test123",
                    "subscription": "sub_inv",
                    "amount_paid": 1200,  # $12.00
                    "currency": "usd",
                    "hosted_invoice_url": "https://stripe.example/i/x",
                    "status_transitions": {
                        "paid_at": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
                    },
                }
            },
        },
    )
    await apply_stripe_event(db_session, event)

    invoice = (
        await db_session.execute(
            select(Invoice).where(Invoice.provider_payment_id == "in_test123")
        )
    ).scalar_one()
    assert invoice.amount == Decimal("12.00")
    assert invoice.currency == "USD"
    assert invoice.status == "paid"


@pytest.mark.asyncio
async def test_invoice_failed_marks_past_due(db_session):
    free, pro = await _seed_plans(db_session)
    user = User(email="fail@example.test")
    db_session.add(user)
    await db_session.flush()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status=SubscriptionStatus.ACTIVE.value,
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_fail",
    )
    db_session.add(sub)
    await db_session.flush()

    event = ProviderEvent(
        type="invoice.payment_failed",
        subscription_id_provider="sub_fail",
        customer_id_provider=None,
        status=None,
        raw={
            "type": "invoice.payment_failed",
            "data": {"object": {"id": "in_fail", "subscription": "sub_fail"}},
        },
    )
    await apply_stripe_event(db_session, event)
    await db_session.refresh(sub)
    assert sub.status == "past_due"


@pytest.mark.asyncio
async def test_unknown_subscription_event_is_ignored(db_session):
    await _seed_plans(db_session)
    event = ProviderEvent(
        type="customer.subscription.updated",
        subscription_id_provider="sub_unknown",
        customer_id_provider="cus_x",
        status="active",
        raw={
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_unknown", "status": "active"}},
        },
    )
    # Should not raise; just logs and persists the BillingEvent.
    await apply_stripe_event(db_session, event)
    audit = (
        await db_session.execute(
            select(BillingEvent).where(BillingEvent.type == "stripe.customer.subscription.updated")
        )
    ).scalar_one_or_none()
    assert audit is not None
