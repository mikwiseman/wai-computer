"""Tests for promo-code bug fixes (10/12/13/14) and admin subscription management.

Covers QA feedback:
- 10: reuse an archived code's name; block only non-archived duplicates.
- 12: extend a promo's expiry via PATCH.
- 14: allow a full 100% discount.
- 76: admin edits subscription dates/params + on-demand Tinkoff renewal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AdminAuditLog
from app.models.billing import Plan, Subscription
from app.models.user import User
from tests.test_admin_console import _grant_admin, _register

# --------------------------------------------------------------------------- #
# Part A — promo codes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_promo_name_reuse_blocked_while_active_allowed_after_archive(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "promo-reuse-admin@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    body = {
        "code": "REUSEME",
        "promotion_type": "access",
        "duration_days": 30,
        "max_redemptions": 1,
        "expires_days": 30,
    }
    first = await client.post("/api/admin/promo-codes", headers=admin_headers, json=body)
    assert first.status_code == 200, first.text

    # Same name while the first is active/non-archived -> blocked.
    dup = await client.post("/api/admin/promo-codes", headers=admin_headers, json=body)
    assert dup.status_code == 409

    # Archive the first, then the name is free to recreate.
    archived = await client.delete(
        f"/api/admin/promo-codes/{first.json()['id']}", headers=admin_headers
    )
    assert archived.status_code == 204

    recreated = await client.post("/api/admin/promo-codes", headers=admin_headers, json=body)
    assert recreated.status_code == 200, recreated.text
    assert recreated.json()["id"] != first.json()["id"]


@pytest.mark.asyncio
async def test_promo_redemption_resolves_active_when_archived_duplicate_exists(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """A claim must not raise MultipleResultsFound when an archived twin exists."""
    admin_payload, admin_headers = await _register(client, "promo-dup-admin@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    user_payload, user_headers = await _register(client, "promo-dup-user@example.com")

    body = {
        "code": "TWINCODE",
        "promotion_type": "access",
        "duration_days": 30,
        "max_redemptions": 1,
    }
    first = await client.post("/api/admin/promo-codes", headers=admin_headers, json=body)
    assert first.status_code == 200
    await client.delete(f"/api/admin/promo-codes/{first.json()['id']}", headers=admin_headers)
    second = await client.post("/api/admin/promo-codes", headers=admin_headers, json=body)
    assert second.status_code == 200

    claim = await client.post(
        "/api/billing/promo/claim", headers=user_headers, json={"code": "TWINCODE"}
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["plan"]["code"] == "pro"


@pytest.mark.asyncio
async def test_promo_discount_allows_full_100_percent_but_rejects_over(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "promo-100-admin@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    full = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={
            "code": "FULLOFF",
            "promotion_type": "discount",
            "billing_period": "month",
            "discount_percent": 100,
            "max_redemptions": 1,
        },
    )
    assert full.status_code == 200, full.text
    assert full.json()["discount_percent"] == 100

    too_much = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={
            "code": "OVEROFF",
            "promotion_type": "discount",
            "billing_period": "month",
            "discount_percent": 101,
            "max_redemptions": 1,
        },
    )
    assert too_much.status_code == 422


@pytest.mark.asyncio
async def test_promo_patch_extends_expiry(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "promo-expiry-admin@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    created = await client.post(
        "/api/admin/promo-codes",
        headers=admin_headers,
        json={"code": "EXTENDME", "promotion_type": "access", "duration_days": 30,
              "max_redemptions": 1, "expires_days": 10},
    )
    assert created.status_code == 200
    new_expiry = (datetime.now(timezone.utc) + timedelta(days=90)).replace(microsecond=0)
    patched = await client.patch(
        f"/api/admin/promo-codes/{created.json()['id']}",
        headers=admin_headers,
        json={"expires_at": new_expiry.isoformat()},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["expires_at"].startswith(new_expiry.date().isoformat())


# --------------------------------------------------------------------------- #
# Part B — subscription management
# --------------------------------------------------------------------------- #


async def _make_subscription(
    db: AsyncSession,
    user_id,
    *,
    provider: str,
    **overrides,
) -> Subscription:
    plan = (await db.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    now = datetime.now(timezone.utc)
    defaults = dict(
        user_id=user_id,
        plan_id=plan.id,
        status="active",
        provider=provider,
        billing_period="month",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        cancel_at_period_end=False,
    )
    defaults.update(overrides)
    sub = Subscription(**defaults)
    db.add(sub)
    await db.flush()
    user = await db.get(User, user_id)
    user.current_subscription_id = sub.id
    await db.flush()
    return sub


@pytest.mark.asyncio
async def test_admin_patch_tinkoff_subscription_writes_dates_and_audits_diff(
    client: AsyncClient,
    db_session: AsyncSession,
):
    admin_payload, admin_headers = await _register(client, "sub-patch-admin@example.com")
    user_payload, _ = await _register(client, "sub-patch-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    sub = await _make_subscription(
        db_session,
        user_payload["user_id"],
        provider="tinkoff",
        tinkoff_rebill_id="rb_1",
        tinkoff_next_charge_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    backdated = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)
    resp = await client.patch(
        f"/api/admin/subscriptions/{sub.id}",
        headers=admin_headers,
        json={
            "next_charge_at": backdated.isoformat(),
            "billing_period": "year",
            "reason": "QA: backdate to fire renewal",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["billing_period"] == "year"
    assert body["tinkoff_next_charge_at"].startswith(backdated.date().isoformat())

    # The billing list must surface the next-charge date too (UI prefill + QA check).
    listing = await client.get("/api/admin/billing", headers=admin_headers)
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["id"] == str(sub.id))
    assert item["tinkoff_next_charge_at"].startswith(backdated.date().isoformat())

    audit_count = (
        await db_session.execute(
            select(func.count(AdminAuditLog.id)).where(
                AdminAuditLog.action == "subscription_update"
            )
        )
    ).scalar_one()
    assert audit_count == 1


@pytest.mark.asyncio
async def test_admin_patch_stripe_subscription_calls_provider_not_db(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    admin_payload, admin_headers = await _register(client, "sub-stripe-admin@example.com")
    user_payload, _ = await _register(client, "sub-stripe-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])
    original_end = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0)
    sub = await _make_subscription(
        db_session,
        user_payload["user_id"],
        provider="stripe",
        stripe_subscription_id="sub_stripe_1",
        current_period_end=original_end,
    )

    calls: list[dict] = []

    async def fake_update(self, sid, **kwargs):
        calls.append({"sid": sid, **kwargs})
        return {"id": sid}

    monkeypatch.setattr(
        "app.billing.providers.stripe_provider.StripeProvider.update_subscription",
        fake_update,
        raising=False,
    )

    target = (datetime.now(timezone.utc) + timedelta(days=60)).replace(microsecond=0)
    resp = await client.patch(
        f"/api/admin/subscriptions/{sub.id}",
        headers=admin_headers,
        json={"next_charge_at": target.isoformat(), "reason": "push stripe renewal"},
    )
    assert resp.status_code == 200, resp.text
    assert len(calls) == 1
    assert calls[0]["sid"] == "sub_stripe_1"
    assert int(calls[0]["trial_end"]) == int(target.timestamp())

    # Provider-owned date is NOT blindly written to our DB (webhook reconciles).
    await db_session.refresh(sub)
    assert sub.current_period_end == original_end


@pytest.mark.asyncio
async def test_admin_run_renewal_charges_tinkoff_and_skips_canceled(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    admin_payload, admin_headers = await _register(client, "renew-admin@example.com")
    user_payload, _ = await _register(client, "renew-user@example.com")
    await _grant_admin(db_session, admin_payload["user_id"])

    # Give the pro plan a Tinkoff price so the charge has an amount.
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    plan.tinkoff_amount_rub_monthly = 990
    await db_session.flush()

    sub = await _make_subscription(
        db_session,
        user_payload["user_id"],
        provider="tinkoff",
        tinkoff_rebill_id="rb_renew",
        tinkoff_order_id="ord_renew",
        tinkoff_next_charge_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    charge_calls: list[str] = []

    async def fake_charge(
        self, *, rebill_id, amount_kopecks, description, customer_email, user_id, order_id
    ):
        charge_calls.append(rebill_id)
        return {"Status": "CONFIRMED", "OrderId": "ord_renew", "PaymentId": "pay_1",
                "Amount": amount_kopecks}

    monkeypatch.setattr(
        "app.billing.providers.tinkoff_provider.TinkoffProvider.charge_rebill",
        fake_charge,
        raising=False,
    )

    ran = await client.post(
        f"/api/admin/subscriptions/{sub.id}/run-renewal", headers=admin_headers, json={}
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["charged"] is True
    assert charge_calls == ["rb_renew"]

    # Cancel pending -> renewal must be skipped (no double charge).
    sub.cancel_at_period_end = True
    await db_session.flush()
    charge_calls.clear()
    skipped = await client.post(
        f"/api/admin/subscriptions/{sub.id}/run-renewal", headers=admin_headers, json={}
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["charged"] is False
    assert charge_calls == []
