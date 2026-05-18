"""Subscription state service — provider-agnostic mutations on Subscription rows."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import ProviderEvent
from app.models.billing import BillingEvent, Plan, Subscription, SubscriptionStatus
from app.models.user import User

logger = logging.getLogger(__name__)


async def _free_plan(db: AsyncSession) -> Plan:
    plan = (await db.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if plan is None:
        raise RuntimeError("Free plan missing — seed migration not applied?")
    return plan


def _ts(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


async def apply_stripe_event(db: AsyncSession, event: ProviderEvent) -> None:
    """Apply a normalized Stripe event to the local subscription state.

    Only mutates rows we already own (looked up by stripe_subscription_id) or
    creates new ones from ``checkout.session.completed`` when the session
    references a known user via ``client_reference_id``.
    """
    raw = event.raw
    data_object = raw.get("data", {}).get("object", {}) if isinstance(raw, dict) else {}

    # 1) Persist the raw event for audit/debug regardless of dispatch.
    db.add(
        BillingEvent(
            subscription_id=None,
            type=f"stripe.{event.type}",
            payload=raw if isinstance(raw, dict) else {"raw": str(raw)},
        )
    )
    await db.flush()

    if event.type == "checkout.session.completed":
        await _handle_checkout_completed(db, data_object)
        return

    if event.type.startswith("customer.subscription."):
        await _handle_subscription_change(db, data_object, event)
        return

    if event.type in {"invoice.paid", "invoice.payment_succeeded"}:
        await _handle_invoice_paid(db, data_object)
        return

    if event.type == "invoice.payment_failed":
        await _handle_invoice_failed(db, data_object)
        return

    logger.info("Stripe event %s ignored (no handler)", event.type)


async def _handle_checkout_completed(db: AsyncSession, obj: dict) -> None:
    user_id = obj.get("client_reference_id")
    provider_subscription_id = obj.get("subscription")
    customer_id = obj.get("customer")
    metadata = obj.get("metadata") or {}
    plan_code = metadata.get("plan_code") or "pro"
    period = metadata.get("period") or "month"

    if not user_id or not provider_subscription_id:
        logger.warning(
            "checkout.session.completed missing client_reference_id or subscription"
        )
        return

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        logger.warning("checkout.session.completed for unknown user_id=%s", user_id)
        return

    plan = (
        await db.execute(select(Plan).where(Plan.code == plan_code))
    ).scalar_one_or_none()
    if plan is None:
        plan = await _free_plan(db)

    existing = (
        await db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == provider_subscription_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        sub = existing
    else:
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            provider="stripe",
            billing_period=period,
            stripe_subscription_id=provider_subscription_id,
            stripe_customer_id=customer_id,
        )
        db.add(sub)
        await db.flush()

    user.current_subscription_id = sub.id
    await db.flush()


async def _handle_subscription_change(
    db: AsyncSession, obj: dict, event: ProviderEvent
) -> None:
    sub_id = obj.get("id")
    if not sub_id:
        return
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        # We may receive subscription.created before checkout.session.completed in
        # rare orderings; ignore — checkout.completed will pick up the row.
        logger.info("Stripe subscription %s not tracked locally, skipping", sub_id)
        return

    if event.status:
        sub.status = event.status
    sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    sub.current_period_start = _ts(obj.get("current_period_start"))
    sub.current_period_end = _ts(obj.get("current_period_end"))
    sub.canceled_at = _ts(obj.get("canceled_at"))
    sub.trial_end = _ts(obj.get("trial_end"))
    await db.flush()


async def _handle_invoice_paid(db: AsyncSession, obj: dict) -> None:
    sub_id = obj.get("subscription")
    if not sub_id:
        return
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        return

    from decimal import Decimal

    from app.models.billing import Invoice

    amount = obj.get("amount_paid") or obj.get("amount_due") or 0
    db.add(
        Invoice(
            subscription_id=sub.id,
            amount=Decimal(amount) / Decimal(100),
            currency=(obj.get("currency") or "usd").upper(),
            status="paid",
            provider_payment_id=obj.get("id"),
            paid_at=_ts(obj.get("status_transitions", {}).get("paid_at")),
            receipt_url=obj.get("hosted_invoice_url"),
        )
    )
    sub.status = SubscriptionStatus.ACTIVE.value
    await db.flush()


async def _handle_invoice_failed(db: AsyncSession, obj: dict) -> None:
    sub_id = obj.get("subscription")
    if not sub_id:
        return
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        return
    sub.status = SubscriptionStatus.PAST_DUE.value
    await db.flush()
