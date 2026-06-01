"""Subscription state service — provider-agnostic mutations on Subscription rows."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import ProviderEvent
from app.core.email import send_charge_confirmation_email
from app.models.billing import (
    BillingEvent,
    BillingPeriod,
    BillingPromoCode,
    BillingPromoRedemption,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from app.models.user import User

logger = logging.getLogger(__name__)


async def _free_plan(db: AsyncSession) -> Plan:
    plan = (await db.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if plan is None:
        raise RuntimeError("Free plan missing — seed migration not applied?")
    return plan


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _record_promo_redemption(
    db: AsyncSession,
    *,
    promo_code_id: uuid.UUID | None,
    user_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> None:
    if promo_code_id is None:
        return
    promo = await db.get(BillingPromoCode, promo_code_id, with_for_update=True)
    if promo is None:
        logger.warning("checkout completed with unknown promo_code_id=%s", promo_code_id)
        return
    existing = (
        await db.execute(
            select(BillingPromoRedemption).where(
                BillingPromoRedemption.promo_code_id == promo_code_id,
                BillingPromoRedemption.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        BillingPromoRedemption(
            promo_code_id=promo_code_id,
            user_id=user_id,
            subscription_id=subscription_id,
        )
    )
    if promo.redeemed_count < promo.max_redemptions:
        promo.redeemed_count += 1


def _ts(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _normalized_billing_period(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {p.value for p in BillingPeriod} else None


def _amount_kopecks(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _plan_amount_kopecks(plan: Plan, period: str) -> int | None:
    amount = (
        plan.tinkoff_amount_rub_yearly
        if period == BillingPeriod.YEAR.value
        else plan.tinkoff_amount_rub_monthly
    )
    if amount is None:
        return None
    return int(Decimal(amount) * 100)


def _resolve_tinkoff_period(
    *,
    raw: dict,
    plan: Plan,
    existing_subscription: Subscription | None,
) -> str:
    raw_period = _normalized_billing_period(raw.get("period"))
    if raw_period is not None:
        return raw_period

    existing_period = _normalized_billing_period(
        existing_subscription.billing_period if existing_subscription is not None else None
    )
    if existing_period is not None:
        return existing_period

    amount = _amount_kopecks(raw.get("amount"))
    if amount is not None:
        for period in (BillingPeriod.MONTH.value, BillingPeriod.YEAR.value):
            if amount == _plan_amount_kopecks(plan, period):
                return period

    return BillingPeriod.MONTH.value


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
    promo_code_id = _uuid_or_none(metadata.get("promo_code_id"))

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
            promo_code_id=promo_code_id,
            stripe_subscription_id=provider_subscription_id,
            stripe_customer_id=customer_id,
        )
        db.add(sub)
        await db.flush()
    if promo_code_id is not None and sub.promo_code_id is None:
        sub.promo_code_id = promo_code_id

    # Mirror the Stripe Customer id onto the User so the Customer Portal
    # opens without a lazy `customers.create_async` round-trip next time.
    if customer_id and user.stripe_customer_id != customer_id:
        user.stripe_customer_id = customer_id

    user.current_subscription_id = sub.id
    await _record_promo_redemption(
        db,
        promo_code_id=sub.promo_code_id,
        user_id=user.id,
        subscription_id=sub.id,
    )
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

    provider_payment_id = obj.get("id")
    if provider_payment_id:
        existing_invoice = (
            await db.execute(
                select(Invoice).where(
                    Invoice.subscription_id == sub.id,
                    Invoice.provider_payment_id == provider_payment_id,
                )
            )
        ).scalar_one_or_none()
        if existing_invoice is not None:
            sub.status = SubscriptionStatus.ACTIVE.value
            await db.flush()
            return

    amount = obj.get("amount_paid") or obj.get("amount_due") or 0
    db.add(
        Invoice(
            subscription_id=sub.id,
            amount=Decimal(amount) / Decimal(100),
            currency=(obj.get("currency") or "usd").upper(),
            status="paid",
            provider_payment_id=provider_payment_id,
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
    from app.models.billing import Invoice

    raw = event.raw  # dict shape from TinkoffProvider.parse_webhook
    order_id = raw.get("order_id")
    rebill_id = raw.get("rebill_id")
    customer_key = event.customer_id_provider
    amount = raw.get("amount")
    raw_payload = raw.get("payload", {})
    promo_code_id = _uuid_or_none(raw.get("promo_code_id"))

    # Persist audit row regardless of dispatch outcome.
    billing_event = BillingEvent(
        subscription_id=None,
        type=f"tinkoff.{(raw.get('status') or 'unknown').lower()}",
        payload=raw_payload if isinstance(raw_payload, dict) else {"payload": raw_payload},
    )
    db.add(billing_event)
    await db.flush()

    if not order_id and not rebill_id:
        logger.info("Tinkoff event without OrderId/RebillId — skipping dispatch")
        return

    customer_user: User | None = None
    if customer_key:
        customer_user = (
            await db.execute(select(User).where(User.id == customer_key))
        ).scalar_one_or_none()

    # Locate subscription: prefer matching RebillId, then user via CustomerKey.
    sub: Subscription | None = None
    if rebill_id:
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.tinkoff_rebill_id == rebill_id)
            )
        ).scalar_one_or_none()
    if sub is None and order_id:
        sub = (
            await db.execute(
                select(Subscription).where(
                    Subscription.tinkoff_order_id == order_id,
                    Subscription.provider == "tinkoff",
                )
            )
        ).scalar_one_or_none()
    if sub is None and customer_key:
        candidates = (
            await db.execute(
                select(Subscription).where(
                    Subscription.tinkoff_customer_key == customer_key,
                    Subscription.provider == "tinkoff",
                )
                .order_by(Subscription.updated_at.desc(), Subscription.created_at.desc())
            )
        ).scalars().all()
        if customer_user is not None and customer_user.current_subscription_id is not None:
            sub = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.id == customer_user.current_subscription_id
                ),
                None,
            )
        if sub is None:
            sub = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.status
                    in {
                        SubscriptionStatus.ACTIVE.value,
                        SubscriptionStatus.TRIALING.value,
                        SubscriptionStatus.INCOMPLETE.value,
                    }
                ),
                None,
            )
        if sub is None and candidates:
            sub = candidates[0]

    plan_code = str(raw.get("plan_code") or "pro").strip().lower() or "pro"
    pro_plan = (
        await db.execute(select(Plan).where(Plan.code == plan_code))
    ).scalar_one_or_none()

    should_activate = event.status == SubscriptionStatus.ACTIVE.value
    if sub is None and not should_activate:
        logger.info(
            "Tinkoff %s event for unknown subscription/customer=%s skipped",
            raw.get("status") or "unknown",
            customer_key or "unknown",
        )
        return

    if sub is None:
        # First notification — create a Subscription tied to the user.
        if not customer_key:
            logger.warning("Tinkoff CONFIRMED event without CustomerKey, cannot create sub")
            return
        if pro_plan is None:
            logger.warning("Plan %s missing; cannot create Tinkoff subscription", plan_code)
            return
        user = customer_user
        if user is None:
            logger.warning("Tinkoff event references unknown user_id=%s", customer_key)
            return
        billing_period = _resolve_tinkoff_period(
            raw=raw,
            plan=pro_plan,
            existing_subscription=None,
        )
        sub = Subscription(
            user_id=user.id,
            plan_id=pro_plan.id,
            status=event.status or SubscriptionStatus.INCOMPLETE.value,
            provider="tinkoff",
            billing_period=billing_period,
            promo_code_id=promo_code_id,
            tinkoff_order_id=order_id,
            tinkoff_customer_key=customer_key,
            tinkoff_rebill_id=rebill_id,
        )
        db.add(sub)
        await db.flush()
        user.current_subscription_id = sub.id
    else:
        existing_plan = pro_plan or await db.get(Plan, sub.plan_id)
        if existing_plan is not None:
            sub.billing_period = _resolve_tinkoff_period(
                raw=raw,
                plan=existing_plan,
                existing_subscription=sub,
            )
        if should_activate:
            user = customer_user
            if user is None or user.id != sub.user_id:
                user = await db.get(User, sub.user_id)
            if user is not None and user.current_subscription_id != sub.id:
                user.current_subscription_id = sub.id
        if promo_code_id is not None and sub.promo_code_id is None:
            sub.promo_code_id = promo_code_id

    billing_event.subscription_id = sub.id

    # Update sub state.
    if event.status:
        sub.status = event.status
    if order_id and sub.tinkoff_order_id is None:
        sub.tinkoff_order_id = order_id
    if rebill_id and sub.tinkoff_rebill_id != rebill_id:
        sub.tinkoff_rebill_id = rebill_id

    if event.status == "active":
        await _record_promo_redemption(
            db,
            promo_code_id=sub.promo_code_id,
            user_id=sub.user_id,
            subscription_id=sub.id,
        )
        payment_id = raw.get("payment_id")
        existing_invoice = None
        if payment_id:
            existing_invoice = (
                await db.execute(
                    select(Invoice).where(
                        Invoice.subscription_id == sub.id,
                        Invoice.provider_payment_id == payment_id,
                    )
                )
            ).scalar_one_or_none()
        if existing_invoice is not None:
            await db.flush()
            return

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
                    provider_payment_id=payment_id,
                    paid_at=now,
                    receipt_url=None,
                )
            )
            # Notify the user of every successful charge (T-Bank recurrent
            # requirement). This is the single point both the first payment and
            # each renewal flow through, and it runs only when a fresh invoice
            # was created, so the user gets exactly one receipt per charge.
            # Best-effort: a mail failure must not roll back the charge.
            charge_user = (
                customer_user
                if customer_user is not None and customer_user.id == sub.user_id
                else await db.get(User, sub.user_id)
            )
            if charge_user is not None:
                await send_charge_confirmation_email(
                    charge_user.email,
                    amount=Decimal(int(amount)) / Decimal(100),
                    currency="RUB",
                    period=sub.billing_period,
                    next_charge_at=sub.tinkoff_next_charge_at,
                    locale=charge_user.region,
                )

    await db.flush()
