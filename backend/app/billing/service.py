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


# ---------------------------------------------------------------------------
# T-Bank rail
# ---------------------------------------------------------------------------


async def apply_tinkoff_event(db: AsyncSession, event: ProviderEvent) -> None:
    """Apply a normalized T-Bank webhook event to the local state.

    We key subscriptions by ``OrderId`` (which we set during Init); the first
    CONFIRMED notification carries a ``RebillId`` which becomes the long-term
    key for recurring charges.
    """
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from app.models.billing import Invoice, Plan, Subscription

    raw = event.raw  # dict shape from TinkoffProvider.parse_webhook
    order_id = raw.get("order_id")
    rebill_id = raw.get("rebill_id")
    customer_key = event.customer_id_provider
    amount = raw.get("amount")
    raw_payload = raw.get("payload", {})

    # Persist audit row regardless of dispatch outcome.
    db.add(
        BillingEvent(
            subscription_id=None,
            type=f"tinkoff.{(raw.get('status') or 'unknown').lower()}",
            payload=raw_payload if isinstance(raw_payload, dict) else {"payload": raw_payload},
        )
    )
    await db.flush()

    if not order_id and not rebill_id:
        logger.info("Tinkoff event without OrderId/RebillId — skipping dispatch")
        return

    # Locate subscription: prefer matching RebillId, then user via CustomerKey.
    sub: Subscription | None = None
    if rebill_id:
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.tinkoff_rebill_id == rebill_id)
            )
        ).scalar_one_or_none()
    if sub is None and customer_key:
        sub = (
            await db.execute(
                select(Subscription).where(
                    Subscription.tinkoff_customer_key == customer_key,
                    Subscription.provider == "tinkoff",
                )
            )
        ).scalar_one_or_none()

    pro_plan = (
        await db.execute(select(Plan).where(Plan.code == "pro"))
    ).scalar_one_or_none()

    if sub is None:
        # First notification — create a Subscription tied to the user.
        if not customer_key:
            logger.warning("Tinkoff CONFIRMED event without CustomerKey, cannot create sub")
            return
        if pro_plan is None:
            logger.warning("Pro plan missing; cannot create Tinkoff subscription")
            return
        from app.models.user import User

        user = (
            await db.execute(select(User).where(User.id == customer_key))
        ).scalar_one_or_none()
        if user is None:
            logger.warning("Tinkoff event references unknown user_id=%s", customer_key)
            return
        sub = Subscription(
            user_id=user.id,
            plan_id=pro_plan.id,
            status=event.status or SubscriptionStatus.INCOMPLETE.value,
            provider="tinkoff",
            billing_period="month",  # T-Bank doesn't carry period in webhook; default month.
            tinkoff_customer_key=customer_key,
            tinkoff_rebill_id=rebill_id,
        )
        db.add(sub)
        await db.flush()
        user.current_subscription_id = sub.id

    # Update sub state.
    if event.status:
        sub.status = event.status
    if rebill_id and not sub.tinkoff_rebill_id:
        sub.tinkoff_rebill_id = rebill_id

    if event.status == "active":
        now = datetime.now(timezone.utc)
        sub.current_period_start = sub.current_period_start or now
        # Default monthly cadence — adjust to billing_period when stored.
        if sub.billing_period == "year":
            sub.current_period_end = now + timedelta(days=365)
            sub.tinkoff_next_charge_at = now + timedelta(days=365)
        else:
            sub.current_period_end = now + timedelta(days=30)
            sub.tinkoff_next_charge_at = now + timedelta(days=30)

        if amount:
            db.add(
                Invoice(
                    subscription_id=sub.id,
                    amount=Decimal(int(amount)) / Decimal(100),
                    currency="RUB",
                    status="paid",
                    provider_payment_id=raw.get("payment_id"),
                    paid_at=now,
                    receipt_url=None,
                )
            )

    await db.flush()
