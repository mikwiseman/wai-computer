"""Admin promo-code API tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.promo_codes import hash_promo_code
from app.models.admin import AdminRole, StaffMember
from app.models.billing import BillingPromoCode

LEGAL_ACCEPTANCE = {
    "accepted_legal_terms": True,
    "legal_terms_version": "2026-05-22",
    "legal_privacy_version": "2026-05-22",
}


async def _admin_headers(client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "promo-admin@example.com",
            "password": "testpassword123",
            **LEGAL_ACCEPTANCE,
        },
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    staff_member = StaffMember(user_id=me.json()["id"], status="active")
    db_session.add(staff_member)
    await db_session.flush()
    db_session.add(AdminRole(staff_member_id=staff_member.id, role="owner"))
    await db_session.flush()
    return headers


@pytest.mark.asyncio
async def test_admin_promo_code_rejects_non_admin(client: AsyncClient):
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "not-admin@example.com",
            "password": "testpassword123",
            **LEGAL_ACCEPTANCE,
        },
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    forbidden = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={"duration_days": 30, "max_redemptions": 5},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Admin role required"


@pytest.mark.asyncio
async def test_admin_promo_code_creates_listable_access_code(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers = await _admin_headers(client, db_session)

    response = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={
            "code": "WAI-ADMIN-30",
            "plan": "pro",
            "billing_period": "month",
            "duration_days": 30,
            "max_redemptions": 25,
            "expires_at": "2026-06-10T23:59:59Z",
            "note": "admin test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "WAI-ADMIN-30"
    assert payload["normalized_code"] == "WAIADMIN30"
    assert payload["plan"] == "pro"
    assert payload["promotion_type"] == "access"
    assert payload["billing_period"] == "month"
    assert payload["duration_days"] == 30
    assert payload["discount_percent"] is None
    assert payload["max_redemptions"] == 25
    assert payload["redeemed_count"] == 0
    assert payload["active"] is True
    assert payload["note"] == "admin test"
    assert payload["expires_at"] is not None

    promo = (
        await db_session.execute(
            select(BillingPromoCode).where(
                BillingPromoCode.code_hash == hash_promo_code("WAI-ADMIN-30")
            )
        )
    ).scalar_one()
    assert promo.duration_days == 30
    assert promo.discount_percent is None
    assert promo.max_redemptions == 25
    assert promo.note == "admin test"
    assert promo.expires_at is not None
    assert promo.expires_at == datetime(2026, 6, 10, 23, 59, 59, tzinfo=timezone.utc)

    listed = await client.get("/api/admin/promo-codes", headers=headers)
    assert listed.json()["items"][0]["code"] == "WAI-ADMIN-30"

    invalid_patch = await client.patch(
        f"/api/admin/promo-codes/{payload['id']}",
        headers=headers,
        json={"discount_percent": 10},
    )
    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == (
        "discount_percent is only valid for discount promo codes"
    )


@pytest.mark.asyncio
async def test_admin_promo_code_creates_percent_discount_code(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers = await _admin_headers(client, db_session)

    response = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={
            "code": "WAI-OFF-25",
            "plan": "pro",
            "promotion_type": "discount",
            "billing_period": "year",
            "discount_percent": 25,
            "max_redemptions": 50,
            "expires_at": "2026-07-01T23:59:59Z",
            "note": "annual discount",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "WAI-OFF-25"
    assert payload["promotion_type"] == "discount"
    assert payload["billing_period"] == "year"
    assert payload["duration_days"] is None
    assert payload["discount_percent"] == 25
    assert payload["max_redemptions"] == 50
    assert payload["expires_at"] == "2026-07-01T23:59:59Z"

    promo = (
        await db_session.execute(
            select(BillingPromoCode).where(
                BillingPromoCode.code_hash == hash_promo_code("WAI-OFF-25")
            )
        )
    ).scalar_one()
    assert promo.code == "WAI-OFF-25"
    assert promo.promotion_type == "discount"
    assert promo.duration_days is None
    assert promo.discount_percent == 25

    invalid_patch = await client.patch(
        f"/api/admin/promo-codes/{payload['id']}",
        headers=headers,
        json={"duration_days": 7},
    )
    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["detail"] == "duration_days is only valid for access promo codes"


@pytest.mark.asyncio
async def test_admin_promo_code_rejects_duplicate_code(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers = await _admin_headers(client, db_session)
    payload = {
        "code": "WAI-DUPLICATE",
        "duration_days": 30,
        "max_redemptions": 1,
    }

    first = await client.post("/api/admin/promo-codes", headers=headers, json=payload)
    second = await client.post("/api/admin/promo-codes", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Promo code already exists"


@pytest.mark.asyncio
async def test_admin_promo_code_rejects_ambiguous_promo_shapes(
    client: AsyncClient,
    db_session: AsyncSession,
):
    headers = await _admin_headers(client, db_session)

    missing_duration = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={"code": "WAI-NO-DAYS", "promotion_type": "access", "max_redemptions": 1},
    )
    access_with_discount = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={
            "code": "WAI-BOTH-ACCESS",
            "promotion_type": "access",
            "duration_days": 30,
            "discount_percent": 20,
            "max_redemptions": 1,
        },
    )
    missing_discount = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={"code": "WAI-NO-DISCOUNT", "promotion_type": "discount", "max_redemptions": 1},
    )
    discount_with_days = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={
            "code": "WAI-BOTH-DISCOUNT",
            "promotion_type": "discount",
            "duration_days": 30,
            "discount_percent": 20,
            "max_redemptions": 1,
        },
    )
    double_expiry = await client.post(
        "/api/admin/promo-codes",
        headers=headers,
        json={
            "code": "WAI-DOUBLE-EXPIRY",
            "promotion_type": "access",
            "duration_days": 30,
            "max_redemptions": 1,
            "expires_days": 1,
            "expires_at": "2026-06-01T00:00:00Z",
        },
    )

    assert missing_duration.status_code == 422
    assert access_with_discount.status_code == 422
    assert missing_discount.status_code == 422
    assert discount_with_days.status_code == 422
    assert double_expiry.status_code == 422
