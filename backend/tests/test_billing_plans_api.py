"""Wire-format tests for /api/billing/plans.

These lock down the JSON shape Apple clients depend on: amount fields must
be numbers (not strings), otherwise `Swift.Decimal` decode fails with
`typeMismatch(NSDecimal, …)`.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.billing import Plan


@pytest.mark.asyncio
async def test_billing_plans_amounts_are_numbers_not_strings(
    client: AsyncClient, db_session
):
    db_session.add_all(
        [
            Plan(
                code="free",
                name="Free",
                description="x",
                usd_amount_monthly=Decimal("0.00"),
                usd_amount_yearly=Decimal("0.00"),
                tinkoff_amount_rub_monthly=Decimal("0.00"),
                tinkoff_amount_rub_yearly=Decimal("0.00"),
                word_cap_per_week=10000,
                memory_retention_days=30,
                features={},
            ),
            Plan(
                code="pro",
                name="Pro",
                description="y",
                usd_amount_monthly=Decimal("12.00"),
                usd_amount_yearly=Decimal("96.00"),
                tinkoff_amount_rub_monthly=Decimal("999.00"),
                tinkoff_amount_rub_yearly=Decimal("7999.00"),
                word_cap_per_week=None,
                memory_retention_days=None,
                features={"agents": True},
            ),
        ]
    )
    await db_session.commit()

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
