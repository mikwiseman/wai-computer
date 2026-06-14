"""Regression tests for billing invoice provider payment uniqueness migration."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Invoice, Plan, Subscription
from app.models.user import User


def _load_provider_payment_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "20260614_123000_unique_provider_payment_invoices.py"
    )
    spec = spec_from_file_location("provider_payment_invoice_migration", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


async def _subscription(db_session: AsyncSession, email: str) -> Subscription:
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    user = User(email=email)
    db_session.add(user)
    await db_session.flush()
    subscription = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="tinkoff",
        billing_period="month",
    )
    db_session.add(subscription)
    await db_session.flush()
    return subscription


@pytest.mark.asyncio
async def test_provider_payment_migration_deletes_semantic_duplicate_invoices(
    db_session: AsyncSession,
) -> None:
    migration = _load_provider_payment_migration()
    subscription = await _subscription(db_session, "billing-migration@example.test")

    for paid_at in (
        datetime(2026, 5, 22, 14, 24, 15, 436646, tzinfo=timezone.utc),
        datetime(2026, 5, 22, 14, 24, 15, 439603, tzinfo=timezone.utc),
    ):
        db_session.add(
            Invoice(
                subscription_id=subscription.id,
                amount=Decimal("999.00"),
                currency="RUB",
                status="paid",
                provider_payment_id="duplicate-payment",
                paid_at=paid_at,
                receipt_url=None,
            )
        )
    await db_session.flush()

    await db_session.execute(
        text(migration.REJECT_CONFLICTING_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL)
    )
    await db_session.execute(
        text(migration.DELETE_SEMANTIC_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL)
    )

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.provider_payment_id == "duplicate-payment")
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_provider_payment_migration_rejects_conflicting_duplicate_invoices(
    db_session: AsyncSession,
) -> None:
    migration = _load_provider_payment_migration()
    subscription = await _subscription(db_session, "billing-conflict@example.test")

    for amount in (Decimal("999.00"), Decimal("7999.00")):
        db_session.add(
            Invoice(
                subscription_id=subscription.id,
                amount=amount,
                currency="RUB",
                status="paid",
                provider_payment_id="conflicting-payment",
                paid_at=datetime(2026, 5, 25, 17, 3, tzinfo=timezone.utc),
                receipt_url=None,
            )
        )
    await db_session.flush()

    with pytest.raises(DBAPIError, match="Conflicting duplicate billing invoice"):
        await db_session.execute(
            text(migration.REJECT_CONFLICTING_DUPLICATE_PROVIDER_PAYMENT_IDS_SQL)
        )
    await db_session.rollback()
