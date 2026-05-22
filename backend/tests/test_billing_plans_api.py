"""Wire-format tests for /api/billing/plans.

These lock down the JSON shape Apple clients depend on: amount fields must
be numbers (not strings), otherwise `Swift.Decimal` decode fails with
`typeMismatch(NSDecimal, …)`.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import CheckoutResult, ProviderUnavailableError
from app.models.billing import Plan, Subscription
from app.models.user import User


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
    assert pro["word_cap_per_week"] == 50_000

    free = next(p for p in plans if p["code"] == "free")
    assert free["word_cap_per_week"] == 3_000


@pytest.mark.asyncio
async def test_subscription_endpoint_ignores_past_due_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
):
    register = await client.post(
        "/api/auth/register",
        json={"email": "pastdue.subscription@example.com", "password": "password123"},
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


class _BillingRouteSettings:
    frontend_url = "https://wai.computer"
    billing_enforcement_enabled = False


async def _register_for_billing(client: AsyncClient, db_session: AsyncSession, email: str):
    register = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
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
