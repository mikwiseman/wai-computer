"""Tests for the Stripe rail: webhook event normalization + subscription mutations."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
import stripe
from sqlalchemy import select

from app.billing.providers.base import ProviderEvent, ProviderUnavailableError
from app.billing.providers.stripe_provider import StripeProvider, _normalize_status
from app.billing.service import apply_stripe_event
from app.models.billing import (
    BillingEvent,
    BillingPromoCode,
    BillingPromoRedemption,
    Invoice,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.models.user import User


async def _seed_plans(db_session) -> tuple[Plan, Plan]:
    free = (await db_session.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if free is None:
        free = Plan(code="free", name="Free", word_cap_per_week=3000, memory_retention_days=30)
        db_session.add(free)
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one_or_none()
    if pro is None:
        pro = Plan(
            code="pro",
            name="Pro",
            stripe_price_id_monthly="price_test_pro_month",
            stripe_price_id_yearly="price_test_pro_year",
            word_cap_per_week=None,
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


def test_normalize_status_preserves_missing_status():
    assert _normalize_status(None) is None


@pytest.mark.asyncio
async def test_resolve_price_id_raises_provider_unavailable_when_plan_price_missing(
    monkeypatch,
):
    pro = Plan(code="pro", name="Pro")

    class FakeResult:
        def scalar_one_or_none(self):
            return pro

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    @asynccontextmanager
    async def fake_get_db_context():
        yield FakeSession()

    monkeypatch.setattr("app.db.session.get_db_context", fake_get_db_context)

    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")

    with pytest.raises(ProviderUnavailableError, match="no Stripe price id"):
        await p._resolve_price_id(plan_code="pro", period="month")


@pytest.mark.asyncio
async def test_resolve_price_id_raises_provider_unavailable_when_plan_missing(
    monkeypatch,
):
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    @asynccontextmanager
    async def fake_get_db_context():
        yield FakeSession()

    monkeypatch.setattr("app.db.session.get_db_context", fake_get_db_context)

    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")

    with pytest.raises(ProviderUnavailableError, match="not found"):
        await p._resolve_price_id(plan_code="pro", period="month")


@pytest.mark.asyncio
async def test_resolve_price_id_returns_configured_yearly_price(monkeypatch):
    pro = Plan(code="pro", name="Pro", stripe_price_id_yearly="price_year")

    class FakeResult:
        def scalar_one_or_none(self):
            return pro

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    @asynccontextmanager
    async def fake_get_db_context():
        yield FakeSession()

    monkeypatch.setattr("app.db.session.get_db_context", fake_get_db_context)

    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")

    assert await p._resolve_price_id(plan_code="pro", period="year") == "price_year"


@pytest.mark.asyncio
async def test_parse_webhook_rejects_missing_webhook_secret():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="")
    p._webhook_secret = ""

    with pytest.raises(ProviderUnavailableError, match="STRIPE_WEBHOOK_SECRET"):
        await p.parse_webhook(raw_body=b"{}", headers={"stripe-signature": "sig"})


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


@pytest.mark.asyncio
async def test_parse_webhook_extracts_invoice_event_from_recursive_payload():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")

    class FakeEvent:
        def to_dict_recursive(self):
            return {
                "type": "invoice.paid",
                "data": {
                    "object": {
                        "subscription": "sub_invoice",
                        "customer": "cus_invoice",
                    }
                },
            }

    with patch.object(p, "_client_or_raise") as m_client:
        m_client.return_value.construct_event.return_value = FakeEvent()
        result = await p.parse_webhook(
            raw_body=b'{"x":1}',
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert result.type == "invoice.paid"
    assert result.subscription_id_provider == "sub_invoice"
    assert result.customer_id_provider == "cus_invoice"
    assert result.status is None


@pytest.mark.asyncio
async def test_parse_webhook_wraps_invalid_signature_error():
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")

    with patch.object(p, "_client_or_raise") as m_client:
        m_client.return_value.construct_event.side_effect = stripe.SignatureVerificationError(
            "bad signature",
            "sig",
            "payload",
        )
        with pytest.raises(ValueError, match="Invalid Stripe webhook signature"):
            await p.parse_webhook(
                raw_body=b'{"x":1}',
                headers={"stripe-signature": "t=1,v1=fake"},
            )


@pytest.mark.asyncio
async def test_create_checkout_without_trial_does_not_add_trial_params(monkeypatch):
    """Launch billing uses the free word cap, not a hosted-checkout trial."""
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    captured: dict = {}

    class FakeSession:
        id = "cs_test_123"
        url = "https://checkout.stripe.test/session"

    class FakeSessions:
        async def create_async(self, *, params):
            captured.update(params)
            return FakeSession()

    class FakeCheckout:
        sessions = FakeSessions()

    class FakeV1:
        checkout = FakeCheckout()

    class FakeClient:
        v1 = FakeV1()

    async def fake_resolve_price_id(*, plan_code: str, period: str) -> str:
        return "price_test_pro_month"

    monkeypatch.setattr(p, "_client_or_raise", lambda: FakeClient())
    monkeypatch.setattr(p, "_resolve_price_id", fake_resolve_price_id)
    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.get_settings",
        lambda: type("S", (), {"stripe_automatic_tax": False})(),
    )

    result = await p.create_checkout(
        plan_code="pro",
        period="month",
        user_email="billing@example.test",
        user_id="user-1",
        success_url="https://wai.computer/billing/success",
        cancel_url="https://wai.computer/billing/cancel",
        trial_days=14,
    )

    assert result.checkout_url == "https://checkout.stripe.test/session"
    assert "payment_method_collection" not in captured
    assert "trial_period_days" not in captured["subscription_data"]
    assert "trial_settings" not in captured["subscription_data"]


@pytest.mark.asyncio
async def test_create_checkout_attaches_percent_discount_coupon(monkeypatch):
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    captured_session: dict = {}
    captured_coupon: dict = {}

    class FakeCoupon:
        id = "coupon_25"

    class FakeCoupons:
        async def create_async(self, *, params):
            captured_coupon.update(params)
            return FakeCoupon()

    class FakeSession:
        id = "cs_discount"
        url = "https://checkout.stripe.test/discount"

    class FakeSessions:
        async def create_async(self, *, params):
            captured_session.update(params)
            return FakeSession()

    class FakeCheckout:
        sessions = FakeSessions()

    class FakeV1:
        coupons = FakeCoupons()
        checkout = FakeCheckout()

    class FakeClient:
        v1 = FakeV1()

    async def fake_resolve_price_id(*, plan_code: str, period: str) -> str:
        return "price_test_pro_year"

    monkeypatch.setattr(p, "_client_or_raise", lambda: FakeClient())
    monkeypatch.setattr(p, "_resolve_price_id", fake_resolve_price_id)
    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.get_settings",
        lambda: type("S", (), {"stripe_automatic_tax": False})(),
    )

    result = await p.create_checkout(
        plan_code="pro",
        period="year",
        user_email="billing@example.test",
        user_id="user-1",
        success_url="https://wai.computer/billing/success",
        cancel_url="https://wai.computer/billing/cancel",
        discount_percent=25,
        discount_code="WAI-OFF-25",
        promo_code_id="promo-uuid",
    )

    assert result.checkout_url == "https://checkout.stripe.test/discount"
    assert captured_coupon == {
        "percent_off": 25,
        "duration": "once",
        "name": "WAI-OFF-25",
    }
    assert captured_session["discounts"] == [{"coupon": "coupon_25"}]
    assert captured_session["metadata"]["promo_code_id"] == "promo-uuid"
    assert captured_session["subscription_data"]["metadata"]["promo_code_id"] == "promo-uuid"


@pytest.mark.asyncio
async def test_create_checkout_enables_automatic_tax(monkeypatch):
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    captured_session: dict = {}

    class FakeSession:
        id = "cs_tax"
        url = "https://checkout.stripe.test/tax"

    class FakeSessions:
        async def create_async(self, *, params):
            captured_session.update(params)
            return FakeSession()

    class FakeCheckout:
        sessions = FakeSessions()

    class FakeV1:
        checkout = FakeCheckout()

    class FakeClient:
        v1 = FakeV1()

    async def fake_resolve_price_id(*, plan_code: str, period: str) -> str:
        return "price_test_pro_month"

    monkeypatch.setattr(p, "_client_or_raise", lambda: FakeClient())
    monkeypatch.setattr(p, "_resolve_price_id", fake_resolve_price_id)
    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.get_settings",
        lambda: type("S", (), {"stripe_automatic_tax": True})(),
    )

    await p.create_checkout(
        plan_code="pro",
        period="month",
        user_email="billing@example.test",
        user_id="user-1",
        success_url="https://wai.computer/billing/success",
        cancel_url="https://wai.computer/billing/cancel",
    )

    assert captured_session["automatic_tax"] == {"enabled": True}


@pytest.mark.asyncio
async def test_stripe_customer_portal_and_invoice_helpers(monkeypatch):
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    calls: list[tuple[str, dict]] = []

    class FakeCustomer:
        id = "cus_new"

    class FakePortalSession:
        url = "https://billing.stripe.test/session"

    class FakeInvoiceWithToDict:
        def to_dict(self):
            return {"id": "in_to_dict"}

    class FakeInvoiceWithRecursive:
        def to_dict_recursive(self):
            return {"id": "in_recursive"}

    class FakeCustomers:
        async def create_async(self, *, params):
            calls.append(("customer", params))
            return FakeCustomer()

    class FakePortalSessions:
        async def create_async(self, *, params):
            calls.append(("portal", params))
            return FakePortalSession()

    class FakeBillingPortal:
        sessions = FakePortalSessions()

    class FakeInvoices:
        async def list_async(self, *, params):
            calls.append(("invoices", params))
            return type(
                "InvoiceListing",
                (),
                {
                    "data": [
                        FakeInvoiceWithToDict(),
                        FakeInvoiceWithRecursive(),
                        {"id": "in_mapping"},
                    ]
                },
            )()

    class FakeV1:
        customers = FakeCustomers()
        billing_portal = FakeBillingPortal()
        invoices = FakeInvoices()

    class FakeClient:
        v1 = FakeV1()

    monkeypatch.setattr(p, "_client_or_raise", lambda: FakeClient())

    customer_id = await p.ensure_customer(user_id="user-1", email="billing@example.test")
    portal_url = await p.create_portal_session(
        customer_id="cus_new",
        return_url="https://wai.computer/settings",
    )
    invoices = await p.list_customer_invoices(customer_id="cus_new", limit=3)

    assert customer_id == "cus_new"
    assert portal_url == "https://billing.stripe.test/session"
    assert invoices == [
        {"id": "in_to_dict"},
        {"id": "in_recursive"},
        {"id": "in_mapping"},
    ]
    assert calls == [
        ("customer", {"email": "billing@example.test", "metadata": {"user_id": "user-1"}}),
        ("portal", {"customer": "cus_new", "return_url": "https://wai.computer/settings"}),
        ("invoices", {"customer": "cus_new", "limit": 3}),
    ]


@pytest.mark.asyncio
async def test_stripe_admin_subscription_and_refund_operations(monkeypatch):
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    calls: list[tuple[str, str, dict | None]] = []

    class FakeRefund:
        def to_dict(self):
            return {"id": "re_123", "status": "succeeded"}

    class FakeSubscriptions:
        async def update_async(self, subscription_id: str, *, params: dict):
            calls.append(("update", subscription_id, params))

        async def cancel_async(self, subscription_id: str):
            calls.append(("cancel", subscription_id, None))

    class FakeRefunds:
        async def create_async(self, *, params: dict):
            calls.append(("refund", params["payment_intent"], params))
            return FakeRefund()

    class FakeV1:
        subscriptions = FakeSubscriptions()
        refunds = FakeRefunds()

    class FakeClient:
        v1 = FakeV1()

    monkeypatch.setattr(p, "_client_or_raise", lambda: FakeClient())

    await p.cancel_subscription("sub_123")
    await p.cancel_subscription("sub_123", at_period_end=False)
    await p.resume_subscription("sub_123")
    refund = await p.refund_payment("pi_123", amount_minor=500, reason="requested_by_customer")

    assert calls == [
        ("update", "sub_123", {"cancel_at_period_end": True}),
        ("cancel", "sub_123", None),
        ("update", "sub_123", {"cancel_at_period_end": False}),
        (
            "refund",
            "pi_123",
            {
                "payment_intent": "pi_123",
                "amount": 500,
                "reason": "requested_by_customer",
            },
        ),
    ]
    assert refund == {"id": "re_123", "status": "succeeded"}


@pytest.mark.asyncio
async def test_refund_payment_handles_recursive_and_mapping_results(monkeypatch):
    p = StripeProvider(secret_key="sk_test_x", webhook_secret="whsec_x")
    results: list[object] = []

    class FakeRecursiveRefund:
        def to_dict_recursive(self):
            return {"id": "re_recursive"}

    class FakeRefunds:
        async def create_async(self, *, params: dict):
            return results.pop(0)

    class FakeV1:
        refunds = FakeRefunds()

    class FakeClient:
        v1 = FakeV1()

    monkeypatch.setattr(p, "_client_or_raise", lambda: FakeClient())

    results.append(FakeRecursiveRefund())
    assert await p.refund_payment("pi_recursive") == {"id": "re_recursive"}

    results.append({"id": "re_mapping"})
    assert await p.refund_payment("pi_mapping") == {"id": "re_mapping"}


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
async def test_checkout_completed_records_discount_promo_redemption(db_session):
    _, pro = await _seed_plans(db_session)
    user = User(email="checkout.promo@example.test")
    promo = BillingPromoCode(
        code="WAI-OFF-25",
        code_hash="discount-hash",
        plan_id=pro.id,
        promotion_type="discount",
        billing_period="year",
        duration_days=None,
        discount_percent=25,
        max_redemptions=10,
    )
    db_session.add_all([user, promo])
    await db_session.flush()

    event = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider="sub_promo",
        customer_id_provider="cus_promo",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user.id),
                    "subscription": "sub_promo",
                    "customer": "cus_promo",
                    "metadata": {
                        "plan_code": "pro",
                        "period": "year",
                        "promo_code_id": str(promo.id),
                    },
                }
            },
        },
    )
    await apply_stripe_event(db_session, event)

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == "sub_promo")
        )
    ).scalar_one()
    assert sub.promo_code_id == promo.id
    redemption = (
        await db_session.execute(
            select(BillingPromoRedemption).where(BillingPromoRedemption.subscription_id == sub.id)
        )
    ).scalar_one()
    assert redemption.promo_code_id == promo.id
    assert promo.redeemed_count == 1

    await apply_stripe_event(db_session, event)
    redemptions = (
        await db_session.execute(
            select(BillingPromoRedemption).where(BillingPromoRedemption.promo_code_id == promo.id)
        )
    ).scalars().all()
    assert len(redemptions) == 1
    assert promo.redeemed_count == 1


@pytest.mark.asyncio
async def test_checkout_completed_ignores_invalid_promo_metadata(db_session):
    _, pro = await _seed_plans(db_session)
    user = User(email="checkout.bad-promo@example.test")
    db_session.add(user)
    await db_session.flush()

    event = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider="sub_bad_promo",
        customer_id_provider="cus_bad_promo",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user.id),
                    "subscription": "sub_bad_promo",
                    "customer": "cus_bad_promo",
                    "metadata": {
                        "plan_code": "pro",
                        "period": "month",
                        "promo_code_id": "not-a-uuid",
                    },
                }
            },
        },
    )
    await apply_stripe_event(db_session, event)

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == "sub_bad_promo")
        )
    ).scalar_one()
    assert sub.plan_id == pro.id
    assert sub.promo_code_id is None


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
        await db_session.execute(select(Invoice).where(Invoice.provider_payment_id == "in_test123"))
    ).scalar_one()
    assert invoice.amount == Decimal("12.00")
    assert invoice.currency == "USD"
    assert invoice.status == "paid"


@pytest.mark.asyncio
async def test_invoice_paid_is_idempotent_by_invoice_id(db_session):
    _, pro = await _seed_plans(db_session)
    user = User(email="inv-idempotent@example.test")
    db_session.add(user)
    await db_session.flush()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status=SubscriptionStatus.PAST_DUE.value,
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_inv_idempotent",
    )
    db_session.add(sub)
    await db_session.flush()

    event = ProviderEvent(
        type="invoice.paid",
        subscription_id_provider="sub_inv_idempotent",
        customer_id_provider="cus_inv_idempotent",
        status=None,
        raw={
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_idempotent",
                    "subscription": "sub_inv_idempotent",
                    "amount_paid": 1200,
                    "currency": "usd",
                }
            },
        },
    )

    await apply_stripe_event(db_session, event)
    await apply_stripe_event(db_session, event)
    await db_session.refresh(sub)

    invoices = (
        await db_session.execute(
            select(Invoice).where(Invoice.provider_payment_id == "in_idempotent")
        )
    ).scalars().all()
    assert len(invoices) == 1
    assert sub.status == SubscriptionStatus.ACTIVE.value


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


@pytest.mark.asyncio
async def test_unknown_stripe_event_is_audited_and_ignored(db_session):
    await _seed_plans(db_session)
    event = ProviderEvent(
        type="customer.created",
        subscription_id_provider=None,
        customer_id_provider="cus_ignored",
        status=None,
        raw={"type": "customer.created", "data": {"object": {"id": "cus_ignored"}}},
    )

    await apply_stripe_event(db_session, event)

    audit = (
        await db_session.execute(
            select(BillingEvent).where(BillingEvent.type == "stripe.customer.created")
        )
    ).scalar_one()
    assert audit.payload["type"] == "customer.created"


@pytest.mark.asyncio
async def test_checkout_completed_ignores_missing_references(db_session):
    await _seed_plans(db_session)
    missing_user_id = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider=None,
        customer_id_provider="cus_x",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {"object": {"subscription": "sub_missing_user"}},
        },
    )
    missing_subscription = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider=None,
        customer_id_provider="cus_x",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": "user-missing-sub"}},
        },
    )

    await apply_stripe_event(db_session, missing_user_id)
    await apply_stripe_event(db_session, missing_subscription)

    subscriptions = (await db_session.execute(select(Subscription))).scalars().all()
    assert subscriptions == []


@pytest.mark.asyncio
async def test_checkout_completed_for_unknown_user_is_ignored(db_session):
    await _seed_plans(db_session)
    event = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider="sub_unknown_user",
        customer_id_provider="cus_x",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(uuid.uuid4()),
                    "subscription": "sub_unknown_user",
                    "customer": "cus_x",
                }
            },
        },
    )

    await apply_stripe_event(db_session, event)

    subscriptions = (await db_session.execute(select(Subscription))).scalars().all()
    assert subscriptions == []


@pytest.mark.asyncio
async def test_checkout_completed_uses_free_plan_when_metadata_plan_missing(db_session):
    free, _ = await _seed_plans(db_session)
    user = User(email="checkout.free-fallback@example.test")
    db_session.add(user)
    await db_session.flush()

    event = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider="sub_free_fallback",
        customer_id_provider="cus_free",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user.id),
                    "subscription": "sub_free_fallback",
                    "customer": "cus_free",
                    "metadata": {"plan_code": "missing", "period": "year"},
                }
            },
        },
    )

    await apply_stripe_event(db_session, event)

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == "sub_free_fallback")
        )
    ).scalar_one()
    assert sub.plan_id == free.id
    assert sub.billing_period == "year"


@pytest.mark.asyncio
async def test_checkout_completed_reuses_existing_subscription(db_session):
    _, pro = await _seed_plans(db_session)
    user = User(email="checkout.existing@example.test")
    db_session.add(user)
    await db_session.flush()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_existing",
        stripe_customer_id="cus_old",
    )
    db_session.add(sub)
    await db_session.flush()

    event = ProviderEvent(
        type="checkout.session.completed",
        subscription_id_provider="sub_existing",
        customer_id_provider="cus_new",
        status=None,
        raw={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user.id),
                    "subscription": "sub_existing",
                    "customer": "cus_new",
                }
            },
        },
    )

    await apply_stripe_event(db_session, event)
    await db_session.refresh(user)

    subscriptions = (await db_session.execute(select(Subscription))).scalars().all()
    assert subscriptions == [sub]
    assert user.current_subscription_id == sub.id


@pytest.mark.asyncio
async def test_invoice_events_ignore_missing_or_unknown_subscriptions(db_session):
    await _seed_plans(db_session)
    events = [
        ProviderEvent(
            type="invoice.paid",
            subscription_id_provider=None,
            customer_id_provider=None,
            status=None,
            raw={"type": "invoice.paid", "data": {"object": {"id": "in_no_sub"}}},
        ),
        ProviderEvent(
            type="invoice.paid",
            subscription_id_provider="sub_unknown",
            customer_id_provider=None,
            status=None,
            raw={
                "type": "invoice.paid",
                "data": {"object": {"id": "in_unknown", "subscription": "sub_unknown"}},
            },
        ),
        ProviderEvent(
            type="invoice.payment_failed",
            subscription_id_provider=None,
            customer_id_provider=None,
            status=None,
            raw={"type": "invoice.payment_failed", "data": {"object": {"id": "in_fail_no_sub"}}},
        ),
        ProviderEvent(
            type="invoice.payment_failed",
            subscription_id_provider="sub_unknown",
            customer_id_provider=None,
            status=None,
            raw={
                "type": "invoice.payment_failed",
                "data": {"object": {"id": "in_fail_unknown", "subscription": "sub_unknown"}},
            },
        ),
    ]

    for event in events:
        await apply_stripe_event(db_session, event)

    invoices = (await db_session.execute(select(Invoice))).scalars().all()
    assert invoices == []
