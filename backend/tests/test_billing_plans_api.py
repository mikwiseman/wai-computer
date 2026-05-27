"""Wire-format tests for /api/billing/plans.

These lock down the JSON shape Apple clients depend on: amount fields must
be numbers (not strings), otherwise `Swift.Decimal` decode fails with
`typeMismatch(NSDecimal, …)`.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.promo_codes import hash_promo_code
from app.billing.providers.base import CheckoutResult, ProviderUnavailableError
from app.models.billing import (
    BillingEvent,
    BillingPromoCode,
    BillingPromoRedemption,
    Invoice,
    Plan,
    Subscription,
)
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE


@pytest.mark.asyncio
async def test_billing_plans_amounts_are_numbers_not_strings(
    client: AsyncClient,
):
    response = await client.get("/api/billing/plans")
    assert response.status_code == 200
    plans = response.json()
    assert len(plans) == 2

    for plan in plans:
        for key in (
            "usd_amount_monthly",
            "usd_amount_yearly",
            "rub_amount_monthly",
            "rub_amount_yearly",
        ):
            value = plan[key]
            assert value is None or isinstance(value, (int, float)), (
                f"{plan['code']}.{key} must be a JSON number, got {type(value).__name__}={value!r}"
            )

    pro = next(p for p in plans if p["code"] == "pro")
    assert pro["usd_amount_monthly"] == 12.0
    assert pro["rub_amount_monthly"] == 999.0
    assert pro["word_cap_per_week"] is None

    free = next(p for p in plans if p["code"] == "free")
    assert free["word_cap_per_week"] == 3_000


@pytest.mark.asyncio
async def test_subscription_endpoint_ignores_past_due_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    register = await client.post(
        "/api/auth/register",
        json={
            "email": "pastdue.subscription@example.com",
            "password": "password123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert register.status_code == 200
    token = register.json()["access_token"]
    user = (
        await db_session.execute(
            select(User).where(User.email == "pastdue.subscription@example.com")
        )
    ).scalar_one()
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="past_due",
        provider="tinkoff",
        billing_period="month",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["code"] == "free"
    assert payload["status"] == "free"
    assert payload["provider"] is None


@pytest.mark.asyncio
async def test_subscription_endpoint_ignores_expired_promo_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "expired.promo.subscription@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="promo",
        billing_period="month",
        current_period_start=datetime.now(timezone.utc) - timedelta(days=31),
        current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
        cancel_at_period_end=True,
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["code"] == "free"
    assert payload["status"] == "free"
    assert payload["provider"] is None


class _BillingRouteSettings:
    frontend_url = "https://wai.computer"
    billing_enforcement_enabled = False


async def _register_for_billing(client: AsyncClient, db_session: AsyncSession, email: str):
    register = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
    )
    assert register.status_code == 200
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    return register.json()["access_token"], user


@pytest.mark.asyncio
async def test_checkout_rejects_unknown_plan_period_and_provider(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, _ = await _register_for_billing(
        client, db_session, "checkout.validation@example.com"
    )
    headers = {"Authorization": f"Bearer {token}"}

    unknown_plan = await client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan": "enterprise", "period": "month"},
    )
    unknown_period = await client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan": "pro", "period": "weekly"},
    )
    unknown_provider = await client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan": "pro", "period": "month", "provider": "cash"},
    )

    assert unknown_plan.status_code == 400
    assert unknown_plan.json()["detail"] == "Unknown plan"
    assert unknown_period.status_code == 400
    assert unknown_period.json()["detail"] == "Unknown period"
    assert unknown_provider.status_code == 400
    assert unknown_provider.json()["detail"] == "Unknown provider"


@pytest.mark.asyncio
async def test_checkout_defaults_ru_region_to_tinkoff_provider(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "checkout.ru-region@example.com"
    )
    user.region = "ru"
    await db_session.flush()
    captured: dict[str, object] = {}

    class FakeTinkoffProvider:
        async def create_checkout(self, **kwargs):
            captured.update(kwargs)
            return CheckoutResult(
                provider="tinkoff",
                checkout_url="https://pay.tbank.test/session",
                provider_session_id="payment-1",
                provider_order_id="order-1",
            )

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.TinkoffProvider", FakeTinkoffProvider)

    response = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan": "pro", "period": "year"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "tinkoff",
        "checkout_url": "https://pay.tbank.test/session",
    }
    assert captured["success_url"] == (
        "https://wai.computer/billing/success?provider=tinkoff&lang=ru"
    )
    assert captured["cancel_url"] == (
        "https://wai.computer/billing/cancel?provider=tinkoff&lang=ru"
    )
    assert captured["user_email"] == "checkout.ru-region@example.com"
    assert captured["trial_days"] is None

    pending = (
        await db_session.execute(
            select(Subscription).where(Subscription.tinkoff_order_id == "order-1")
        )
    ).scalar_one()
    assert pending.status == "incomplete"
    assert pending.user_id == user.id


@pytest.mark.asyncio
async def test_checkout_applies_percent_discount_promo_code(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, _ = await _register_for_billing(
        client, db_session, "checkout.discount@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    promo = BillingPromoCode(
        code="WAI-OFF-20",
        code_hash=hash_promo_code("WAI-OFF-20"),
        plan_id=pro.id,
        promotion_type="discount",
        billing_period="month",
        duration_days=None,
        discount_percent=20,
        max_redemptions=10,
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(promo)
    await db_session.flush()
    captured: dict[str, object] = {}

    class FakeStripeProvider:
        async def create_checkout(self, **kwargs):
            captured.update(kwargs)
            return CheckoutResult(
                provider="stripe",
                checkout_url="https://checkout.stripe.test/session",
                provider_session_id="cs_1",
            )

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan": "pro",
            "period": "month",
            "provider": "stripe",
            "promo_code": " wai-off-20 ",
        },
    )

    assert response.status_code == 200
    assert captured["discount_percent"] == 20
    assert captured["discount_code"] == "WAI-OFF-20"
    assert captured["promo_code_id"] == str(promo.id)


@pytest.mark.asyncio
async def test_checkout_rejects_discount_promo_for_wrong_period(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, _ = await _register_for_billing(
        client, db_session, "checkout.discount.period@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    db_session.add(
        BillingPromoCode(
            code="WAI-YEAR-20",
            code_hash=hash_promo_code("WAI-YEAR-20"),
            plan_id=pro.id,
            promotion_type="discount",
            billing_period="year",
            duration_days=None,
            discount_percent=20,
            max_redemptions=10,
            expires_at=datetime.now(timezone.utc) + timedelta(days=3),
        )
    )
    await db_session.flush()

    class FakeStripeProvider:
        async def create_checkout(self, **kwargs):
            raise AssertionError("checkout provider must not be called")

    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan": "pro",
            "period": "month",
            "provider": "stripe",
            "promo_code": "WAI-YEAR-20",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Promo code does not apply to selected period"


@pytest.mark.asyncio
async def test_checkout_rejects_invalid_discount_promo_states(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "checkout.discount.invalid@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    expired = BillingPromoCode(
        code="WAI-OLD-20",
        code_hash=hash_promo_code("WAI-OLD-20"),
        plan_id=pro.id,
        promotion_type="discount",
        billing_period="month",
        duration_days=None,
        discount_percent=20,
        max_redemptions=10,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    exhausted = BillingPromoCode(
        code="WAI-USED-UP",
        code_hash=hash_promo_code("WAI-USED-UP"),
        plan_id=pro.id,
        promotion_type="discount",
        billing_period="month",
        duration_days=None,
        discount_percent=20,
        max_redemptions=1,
        redeemed_count=1,
    )
    access = BillingPromoCode(
        code="WAI-FREE-DAYS",
        code_hash=hash_promo_code("WAI-FREE-DAYS"),
        plan_id=pro.id,
        promotion_type="access",
        billing_period="month",
        duration_days=14,
        discount_percent=None,
        max_redemptions=10,
    )
    redeemed = BillingPromoCode(
        code="WAI-ALREADY-20",
        code_hash=hash_promo_code("WAI-ALREADY-20"),
        plan_id=pro.id,
        promotion_type="discount",
        billing_period="month",
        duration_days=None,
        discount_percent=20,
        max_redemptions=10,
    )
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
    )
    db_session.add_all([expired, exhausted, access, redeemed, sub])
    await db_session.flush()
    db_session.add(
        BillingPromoRedemption(
            promo_code_id=redeemed.id,
            user_id=user.id,
            subscription_id=sub.id,
        )
    )
    await db_session.flush()

    class FakeStripeProvider:
        async def create_checkout(self, **kwargs):
            raise AssertionError("checkout provider must not be called")

    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    async def checkout(code: str):
        return await client.post(
            "/api/billing/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"plan": "pro", "period": "month", "provider": "stripe", "promo_code": code},
        )

    not_found = await checkout("WAI-MISSING")
    access_response = await checkout("WAI-FREE-DAYS")
    expired_response = await checkout("WAI-OLD-20")
    exhausted_response = await checkout("WAI-USED-UP")
    redeemed_response = await checkout("WAI-ALREADY-20")

    assert not_found.status_code == 404
    assert access_response.status_code == 400
    assert access_response.json()["detail"] == "Promo code grants Pro access"
    assert expired_response.status_code == 400
    assert expired_response.json()["detail"] == "Promo code expired"
    assert exhausted_response.status_code == 409
    assert exhausted_response.json()["detail"] == "Promo code exhausted"
    assert redeemed_response.status_code == 409
    assert redeemed_response.json()["detail"] == "Promo code already redeemed"


@pytest.mark.asyncio
async def test_checkout_surfaces_provider_unavailable_errors(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, _ = await _register_for_billing(
        client, db_session, "checkout.unavailable@example.com"
    )

    class FakeStripeProvider:
        async def create_checkout(self, **kwargs):
            raise ProviderUnavailableError("missing key")

    class FakeTinkoffProvider:
        async def create_checkout(self, **kwargs):
            raise ProviderUnavailableError("missing terminal")

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)
    monkeypatch.setattr("app.billing.router.TinkoffProvider", FakeTinkoffProvider)

    stripe_response = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan": "pro", "period": "month", "provider": "stripe"},
    )
    tinkoff_response = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan": "pro", "period": "month", "provider": "tinkoff"},
    )

    assert stripe_response.status_code == 503
    assert stripe_response.json()["detail"] == "Stripe checkout unavailable: missing key"
    assert tinkoff_response.status_code == 503
    assert tinkoff_response.json()["detail"] == (
        "T-Bank checkout unavailable: missing terminal"
    )


@pytest.mark.asyncio
async def test_claim_promo_code_creates_non_renewing_pro_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(client, db_session, "promo.claim@example.com")
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    promo = BillingPromoCode(
        code_hash=hash_promo_code("WAI-TEST-30"),
        plan_id=pro.id,
        billing_period="month",
        duration_days=30,
        max_redemptions=1,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        note="test promo",
    )
    db_session.add(promo)
    await db_session.flush()

    response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "wai test 30"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["code"] == "pro"
    assert payload["status"] == "active"
    assert payload["provider"] == "promo"
    assert payload["billing_period"] == "month"
    assert payload["cancel_at_period_end"] is True
    assert payload["current_period_end"] is not None

    await db_session.refresh(user)
    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.id == user.current_subscription_id)
        )
    ).scalar_one()
    assert sub.provider == "promo"
    assert sub.cancel_at_period_end is True
    assert promo.redeemed_count == 1

    redemption = (
        await db_session.execute(
            select(BillingPromoRedemption).where(BillingPromoRedemption.user_id == user.id)
        )
    ).scalar_one()
    assert redemption.subscription_id == sub.id


@pytest.mark.asyncio
async def test_claim_promo_code_rejects_existing_active_promo_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(client, db_session, "promo.double@example.com")
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    active_sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="promo",
        billing_period="month",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=10),
        cancel_at_period_end=True,
    )
    second_promo = BillingPromoCode(
        code_hash=hash_promo_code("WAI-SECOND"),
        plan_id=pro.id,
        duration_days=30,
        max_redemptions=1,
    )
    db_session.add_all([active_sub, second_promo])
    await db_session.flush()
    user.current_subscription_id = active_sub.id
    await db_session.flush()

    response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "WAI-SECOND"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Active subscription already exists"
    assert second_promo.redeemed_count == 0


@pytest.mark.asyncio
async def test_claim_promo_code_rejects_invalid_expired_and_exhausted_codes(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, _ = await _register_for_billing(client, db_session, "promo.invalid@example.com")
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    expired = BillingPromoCode(
        code_hash=hash_promo_code("WAI-EXPIRED"),
        plan_id=pro.id,
        duration_days=30,
        max_redemptions=10,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    exhausted = BillingPromoCode(
        code_hash=hash_promo_code("WAI-USED"),
        plan_id=pro.id,
        duration_days=30,
        max_redemptions=1,
        redeemed_count=1,
    )
    db_session.add_all([expired, exhausted])
    await db_session.flush()

    invalid_response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "missing"},
    )
    expired_response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "WAI-EXPIRED"},
    )
    exhausted_response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "WAI-USED"},
    )

    assert invalid_response.status_code == 404
    assert invalid_response.json()["detail"] == "Promo code not found"
    assert expired_response.status_code == 400
    assert expired_response.json()["detail"] == "Promo code expired"
    assert exhausted_response.status_code == 409
    assert exhausted_response.json()["detail"] == "Promo code exhausted"


@pytest.mark.asyncio
async def test_claim_promo_code_rejects_discount_and_corrupt_access_codes(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(client, db_session, "promo.shape@example.com")
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    discount = BillingPromoCode(
        code_hash=hash_promo_code("WAI-DISCOUNT"),
        plan_id=pro.id,
        promotion_type="discount",
        billing_period="month",
        duration_days=None,
        discount_percent=20,
        max_redemptions=10,
    )
    redeemed = BillingPromoCode(
        code_hash=hash_promo_code("WAI-REDEEMED"),
        plan_id=pro.id,
        promotion_type="access",
        billing_period="month",
        duration_days=30,
        max_redemptions=10,
    )
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="expired",
        provider="promo",
        billing_period="month",
    )
    db_session.add_all([discount, redeemed, sub])
    await db_session.flush()
    db_session.add(
        BillingPromoRedemption(
            promo_code_id=redeemed.id,
            user_id=user.id,
            subscription_id=sub.id,
        )
    )
    await db_session.flush()

    discount_response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "WAI-DISCOUNT"},
    )
    redeemed_response = await client.post(
        "/api/billing/promo/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "WAI-REDEEMED"},
    )

    assert discount_response.status_code == 400
    assert discount_response.json()["detail"] == "Promo code applies to checkout"
    assert redeemed_response.status_code == 409
    assert redeemed_response.json()["detail"] == "Promo code already redeemed"


@pytest.mark.asyncio
async def test_cancel_subscription_requires_active_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, _ = await _register_for_billing(
        client, db_session, "cancel.no-subscription@example.com"
    )

    response = await client.post(
        "/api/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No active subscription"


@pytest.mark.asyncio
async def test_cancel_subscription_cancels_stripe_at_period_end(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "cancel.stripe@example.com"
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_cancel",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()
    canceled: list[str] = []

    class FakeStripeProvider:
        async def cancel_subscription(self, provider_subscription_id: str):
            canceled.append(provider_subscription_id)

    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"cancel_at_period_end": True}
    assert canceled == ["sub_cancel"]
    assert sub.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_cancel_subscription_surfaces_stripe_provider_unavailable(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "cancel.stripe-unavailable@example.com"
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_unavailable",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    class FakeStripeProvider:
        async def cancel_subscription(self, provider_subscription_id: str):
            raise ProviderUnavailableError("api down")

    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Stripe subscription unavailable: api down"


@pytest.mark.asyncio
async def test_cancel_subscription_marks_tinkoff_subscription_locally(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "cancel.tinkoff@example.com"
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="tinkoff",
        billing_period="year",
        tinkoff_rebill_id="rebill-cancel",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.post(
        "/api/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"cancel_at_period_end": True}
    assert sub.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_cancel_subscription_rejects_unknown_provider(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "cancel.unknown-provider@example.com"
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="manual",
        billing_period="month",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.post(
        "/api/billing/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown provider on subscription"


@pytest.mark.asyncio
async def test_invoices_endpoint_returns_empty_list_for_new_user(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, _ = await _register_for_billing(client, db_session, "invoices.empty@example.com")

    response = await client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_invoices_endpoint_returns_user_invoices_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "invoices.history@example.com"
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_history",
    )
    db_session.add(sub)
    await db_session.flush()

    older = Invoice(
        subscription_id=sub.id,
        amount=Decimal("12.00"),
        currency="USD",
        status="paid",
        provider_payment_id="in_old",
        paid_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
        created_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
        receipt_url="https://stripe.test/r/old",
    )
    db_session.add(older)
    await db_session.flush()
    newer = Invoice(
        subscription_id=sub.id,
        amount=Decimal("12.00"),
        currency="USD",
        status="paid",
        provider_payment_id="in_new",
        paid_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        receipt_url="https://stripe.test/r/new",
    )
    db_session.add(newer)
    await db_session.flush()

    response = await client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    # Newest first by created_at DESC.
    assert rows[0]["receipt_url"] == "https://stripe.test/r/new"
    assert rows[0]["amount"] == 12.0
    assert rows[0]["currency"] == "USD"
    assert rows[0]["status"] == "paid"
    assert rows[1]["receipt_url"] == "https://stripe.test/r/old"


@pytest.mark.asyncio
async def test_invoices_endpoint_does_not_leak_other_users_invoices(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token_a, user_a = await _register_for_billing(
        client, db_session, "invoices.user-a@example.com"
    )
    _token_b, user_b = await _register_for_billing(
        client, db_session, "invoices.user-b@example.com"
    )
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub_b = Subscription(
        user_id=user_b.id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_user_b",
    )
    db_session.add(sub_b)
    await db_session.flush()
    db_session.add(
        Invoice(
            subscription_id=sub_b.id,
            amount=Decimal("12.00"),
            currency="USD",
            status="paid",
            provider_payment_id="in_b",
            paid_at=datetime.now(timezone.utc),
            receipt_url="https://stripe.test/r/b",
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 200
    assert response.json() == []
    assert user_a.id != user_b.id


@pytest.mark.asyncio
async def test_subscription_endpoint_exposes_next_charge_fields(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "subscription.next-charge@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    next_at = datetime.now(timezone.utc) + timedelta(days=15)
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=next_at,
        stripe_subscription_id="sub_next_charge",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_charge_at"] is not None
    assert payload["next_charge_amount"] == 12.0
    assert payload["next_charge_currency"] == "USD"


@pytest.mark.asyncio
async def test_subscription_endpoint_hides_next_charge_when_canceled_at_period_end(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "subscription.next-charge-canceled@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=15),
        cancel_at_period_end=True,
        stripe_subscription_id="sub_cancel_then_no_charge",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.get(
        "/api/billing/subscription",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_charge_at"] is None
    assert payload["next_charge_amount"] is None
    assert payload["next_charge_currency"] is None
    assert payload["cancel_at_period_end"] is True


@pytest.mark.asyncio
async def test_switch_plan_records_event_and_returns_202(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "switch.plan@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.post(
        "/api/billing/switch-plan",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "yearly"},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "requested_period": "year"}

    events = (
        await db_session.execute(
            select(BillingEvent).where(BillingEvent.subscription_id == sub.id)
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].type == "switch_plan_requested"
    assert events[0].payload["requested_period"] == "year"
    assert events[0].payload["current_period"] == "month"


@pytest.mark.asyncio
async def test_switch_plan_rejects_unknown_period(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, user = await _register_for_billing(
        client, db_session, "switch.plan-bad@example.com"
    )
    pro = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=pro.id,
        status="active",
        provider="stripe",
        billing_period="month",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    response = await client.post(
        "/api/billing/switch-plan",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "weekly"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown period"


@pytest.mark.asyncio
async def test_switch_plan_requires_active_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    token, _ = await _register_for_billing(
        client, db_session, "switch.plan-none@example.com"
    )

    response = await client.post(
        "/api/billing/switch-plan",
        headers={"Authorization": f"Bearer {token}"},
        json={"period": "yearly"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No active subscription"


# ---------------------------------------------------------------------------
# Customer Portal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portal_returns_stripe_session_url_for_existing_customer(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "portal.existing@example.com"
    )
    user.stripe_customer_id = "cus_existing_123"
    await db_session.flush()
    captured: dict[str, object] = {}

    class FakeStripeProvider:
        async def ensure_customer(self, **kwargs):
            raise AssertionError("ensure_customer must not be called when id present")

        async def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
            captured["customer_id"] = customer_id
            captured["return_url"] = return_url
            return "https://billing.stripe.com/p/session_existing"

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/portal",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"url": "https://billing.stripe.com/p/session_existing"}
    assert captured["customer_id"] == "cus_existing_123"
    assert captured["return_url"] == "https://wai.computer/billing"


@pytest.mark.asyncio
async def test_portal_auto_creates_customer_when_user_has_no_stripe_customer_id(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "portal.lazy@example.com"
    )
    ensured: dict[str, str] = {}

    class FakeStripeProvider:
        async def ensure_customer(self, *, user_id: str, email: str) -> str:
            ensured["user_id"] = user_id
            ensured["email"] = email
            return "cus_freshly_created"

        async def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
            assert customer_id == "cus_freshly_created"
            return "https://billing.stripe.com/p/session_new"

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/portal",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"url": "https://billing.stripe.com/p/session_new"}
    assert ensured == {"user_id": str(user.id), "email": "portal.lazy@example.com"}

    await db_session.refresh(user)
    assert user.stripe_customer_id == "cus_freshly_created"


@pytest.mark.asyncio
async def test_portal_returns_502_when_stripe_session_create_fails(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "portal.fail@example.com"
    )
    user.stripe_customer_id = "cus_will_fail"
    await db_session.flush()

    class FakeStripeProvider:
        async def create_portal_session(self, **kwargs):
            raise RuntimeError("Stripe portal not configured for this account")

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/portal",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Stripe portal unavailable"


@pytest.mark.asyncio
async def test_portal_returns_503_when_stripe_unconfigured(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, _ = await _register_for_billing(
        client, db_session, "portal.unavailable@example.com"
    )

    class FakeStripeProvider:
        async def ensure_customer(self, **kwargs):
            raise ProviderUnavailableError("STRIPE_SECRET_KEY not configured")

    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingRouteSettings())
    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/billing/portal",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "Stripe portal unavailable: STRIPE_SECRET_KEY not configured"
    )


# ---------------------------------------------------------------------------
# Invoice merge: local mirror + live Stripe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoices_endpoint_merges_local_and_stripe_invoices(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "invoices.merge@example.com"
    )
    user.stripe_customer_id = "cus_merge"
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_merge",
        stripe_customer_id="cus_merge",
    )
    db_session.add(sub)
    await db_session.flush()

    # Two local rows, one of which mirrors the Stripe id we're about to return.
    db_session.add(
        Invoice(
            subscription_id=sub.id,
            amount=Decimal("12.00"),
            currency="USD",
            status="paid",
            provider_payment_id="in_shared",
            paid_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            receipt_url="https://stripe.test/r/legacy",
        )
    )
    db_session.add(
        Invoice(
            subscription_id=sub.id,
            amount=Decimal("12.00"),
            currency="USD",
            status="paid",
            provider_payment_id="in_local_only",
            paid_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            receipt_url="https://stripe.test/r/old",
        )
    )
    await db_session.flush()

    stripe_invoices = [
        # Shared id — Stripe data must win.
        {
            "id": "in_shared",
            "created": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
            "amount_paid": 1200,
            "amount_due": 1200,
            "currency": "USD",
            "status": "paid",
            "hosted_invoice_url": "https://invoice.stripe.com/i/in_shared",
            "invoice_pdf": "https://pay.stripe.com/i/in_shared.pdf",
            "status_transitions": {
                "paid_at": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
            },
            "lines": {
                "data": [
                    {
                        "period": {
                            "start": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
                            "end": int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()),
                        }
                    }
                ]
            },
            "description": "Subscription update",
        },
        # Stripe-only row, newer than both local rows.
        {
            "id": "in_stripe_only",
            "created": int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()),
            "amount_paid": 1200,
            "currency": "usd",
            "status": "paid",
            "hosted_invoice_url": "https://invoice.stripe.com/i/in_stripe_only",
            "invoice_pdf": "https://pay.stripe.com/i/in_stripe_only.pdf",
            "status_transitions": {
                "paid_at": int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
            },
            "lines": {"data": []},
            "description": None,
        },
    ]

    class FakeStripeProvider:
        async def list_customer_invoices(self, *, customer_id: str, limit: int = 25):
            assert customer_id == "cus_merge"
            assert limit == 25
            return stripe_invoices

    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    rows = response.json()
    # Newest first, all three rows present (Stripe-only + shared (Stripe wins) + local-only).
    ids = [r["id"] for r in rows]
    assert "in_stripe_only" == ids[0]
    assert "in_shared" in ids
    # The local "in_shared" row should be hidden — Stripe wins the merge.
    shared = next(r for r in rows if r["id"] == "in_shared")
    assert shared["hosted_invoice_url"] == "https://invoice.stripe.com/i/in_shared"
    assert shared["invoice_pdf"] == "https://pay.stripe.com/i/in_shared.pdf"
    assert shared["amount"] == 12.0
    assert shared["currency"] == "USD"
    assert shared["period_start"] is not None
    assert shared["period_end"] is not None
    # Stripe-only row exposes the PDF too.
    stripe_only = next(r for r in rows if r["id"] == "in_stripe_only")
    assert stripe_only["invoice_pdf"] == "https://pay.stripe.com/i/in_stripe_only.pdf"
    # And the local-only row should still be present.
    assert any(r.get("receipt_url") == "https://stripe.test/r/old" for r in rows)


@pytest.mark.asyncio
async def test_invoices_endpoint_falls_back_to_local_mirror_when_stripe_fails(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    token, user = await _register_for_billing(
        client, db_session, "invoices.fallback@example.com"
    )
    user.stripe_customer_id = "cus_dead"
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="stripe",
        billing_period="month",
        stripe_subscription_id="sub_dead",
    )
    db_session.add(sub)
    await db_session.flush()
    db_session.add(
        Invoice(
            subscription_id=sub.id,
            amount=Decimal("12.00"),
            currency="USD",
            status="paid",
            provider_payment_id="in_local",
            paid_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            receipt_url="https://stripe.test/r/local",
        )
    )
    await db_session.flush()

    class FakeStripeProvider:
        async def list_customer_invoices(self, **kwargs):
            raise RuntimeError("Stripe down")

    monkeypatch.setattr("app.billing.router.StripeProvider", FakeStripeProvider)

    response = await client.get(
        "/api/billing/invoices",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["receipt_url"] == "https://stripe.test/r/local"


# ---------------------------------------------------------------------------
# Webhook signature failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_webhook_returns_400_for_invalid_signature(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/api/webhooks/stripe` must surface a 400 on signature mismatch.

    Stripe retries on any non-2xx, so reflecting "bad signature" as 400 (not
    500) keeps their retry queue clean while still rejecting forged events.
    """

    class FakeStripeProvider:
        async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]):
            raise ValueError("Invalid Stripe webhook signature: bad sig")

    monkeypatch.setattr("app.billing.webhooks.StripeProvider", FakeStripeProvider)

    response = await client.post(
        "/api/webhooks/stripe",
        content=b'{"type":"invoice.paid"}',
        headers={"stripe-signature": "t=1,v1=forged"},
    )

    assert response.status_code == 400
    assert "Invalid Stripe webhook signature" in response.json()["detail"]
