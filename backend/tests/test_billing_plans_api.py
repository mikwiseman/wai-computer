"""Wire-format tests for /api/billing/plans.

These lock down the JSON shape Apple clients depend on: amount fields must
be numbers (not strings), otherwise `Swift.Decimal` decode fails with
`typeMismatch(NSDecimal, …)`.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
