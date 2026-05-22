"""Admin promo-code API tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.promo_codes import hash_promo_code
from app.models.billing import BillingPromoCode


class _AdminSettings:
    admin_password = "correct-admin-password"


@pytest.mark.asyncio
async def test_admin_promo_code_requires_configured_password(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.api.routes import admin as admin_routes

    settings = type("Settings", (), {"admin_password": ""})()
    monkeypatch.setattr(admin_routes, "get_settings", lambda: settings)

    response = await client.post(
        "/api/admin/promo-codes",
        headers={"X-Wai-Admin-Password": "anything"},
        json={
            "duration_days": 30,
            "max_redemptions": 5,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Admin password is not configured"


@pytest.mark.asyncio
async def test_admin_promo_code_rejects_missing_or_wrong_password(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.api.routes import admin as admin_routes

    monkeypatch.setattr(admin_routes, "get_settings", lambda: _AdminSettings())

    missing = await client.post(
        "/api/admin/promo-codes",
        json={"duration_days": 30, "max_redemptions": 5},
    )
    wrong = await client.post(
        "/api/admin/promo-codes",
        headers={"X-Wai-Admin-Password": "wrong"},
        json={"duration_days": 30, "max_redemptions": 5},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == "Incorrect admin password"
    assert wrong.json()["detail"] == "Incorrect admin password"


@pytest.mark.asyncio
async def test_admin_promo_code_creates_hash_only_code(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.api.routes import admin as admin_routes

    monkeypatch.setattr(admin_routes, "get_settings", lambda: _AdminSettings())

    response = await client.post(
        "/api/admin/promo-codes",
        headers={"X-Wai-Admin-Password": "correct-admin-password"},
        json={
            "code": "WAI-ADMIN-30",
            "plan": "pro",
            "billing_period": "month",
            "duration_days": 30,
            "max_redemptions": 25,
            "expires_days": 14,
            "note": "admin test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "WAI-ADMIN-30"
    assert payload["normalized_code"] == "WAIADMIN30"
    assert payload["plan"] == "pro"
    assert payload["billing_period"] == "month"
    assert payload["duration_days"] == 30
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
    assert promo.max_redemptions == 25
    assert promo.note == "admin test"
    assert promo.expires_at is not None
    assert promo.expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_admin_promo_code_rejects_duplicate_code(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.api.routes import admin as admin_routes

    monkeypatch.setattr(admin_routes, "get_settings", lambda: _AdminSettings())

    payload = {
        "code": "WAI-DUPLICATE",
        "duration_days": 30,
        "max_redemptions": 1,
    }
    first = await client.post(
        "/api/admin/promo-codes",
        headers={"X-Wai-Admin-Password": "correct-admin-password"},
        json=payload,
    )
    second = await client.post(
        "/api/admin/promo-codes",
        headers={"X-Wai-Admin-Password": "correct-admin-password"},
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Promo code already exists"
