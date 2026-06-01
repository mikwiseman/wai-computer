"""Periodic billing renewal tasks."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import ProviderEvent
from app.billing.providers.tinkoff_provider import TinkoffProvider, _normalize_status
from app.billing.service import apply_tinkoff_event
from app.core.email import send_payment_failed_email, send_renewal_reminder_email
from app.db.session import get_db_context
from app.models.billing import BillingEvent, Plan, Subscription, SubscriptionStatus
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Email the user this many days before a recurring charge so they can cancel
# in time (T-Bank recurrent good-practice; especially relevant for yearly).
RENEWAL_REMINDER_LEAD_DAYS = 3


async def charge_due_tinkoff_renewals(
    *,
    limit: int = 50,
    provider_factory: Callable[[], TinkoffProvider] = TinkoffProvider,
    db_session: AsyncSession | None = None,
) -> dict[str, int]:
    """Charge active T-Bank subscriptions whose renewal time has arrived."""
    if db_session is not None:
        return await _charge_due_tinkoff_renewals_in_session(
            db_session,
            limit=limit,
            provider_factory=provider_factory,
        )

    async with get_db_context() as db:
        return await _charge_due_tinkoff_renewals_in_session(
            db,
            limit=limit,
            provider_factory=provider_factory,
        )


async def _charge_due_tinkoff_renewals_in_session(
    db: AsyncSession,
    *,
    limit: int,
    provider_factory: Callable[[], TinkoffProvider],
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    charged = 0
    skipped = 0
    failed = 0
    provider = provider_factory()

    rows = (
        await db.execute(
            select(Subscription, Plan, User)
            .join(Plan, Subscription.plan_id == Plan.id)
            .join(User, Subscription.user_id == User.id)
            .where(
                Subscription.provider == "tinkoff",
                Subscription.status == SubscriptionStatus.ACTIVE.value,
                Subscription.cancel_at_period_end.is_(False),
                Subscription.tinkoff_rebill_id.is_not(None),
                Subscription.tinkoff_next_charge_at.is_not(None),
                Subscription.tinkoff_next_charge_at <= now,
            )
            .order_by(Subscription.tinkoff_next_charge_at.asc())
            .limit(limit)
        )
    ).all()

    for sub, plan, user in rows:
        result = await charge_tinkoff_subscription(db, sub, plan, user, provider)
        if result == "charged":
            charged += 1
        elif result == "skipped":
            skipped += 1
        else:
            failed += 1

    return {"charged": charged, "skipped": skipped, "failed": failed}


async def charge_tinkoff_subscription(
    db: AsyncSession,
    sub: Subscription,
    plan: Plan,
    user: User,
    provider: TinkoffProvider,
) -> str:
    """Charge one Tinkoff subscription's rebill.

    Shared by the periodic renewal task and the admin "run renewal now" action.
    Returns ``"charged"`` | ``"skipped"`` (no Tinkoff amount on the plan) |
    ``"failed"`` (marks the subscription PAST_DUE, matching the batch task).
    """
    amount_rub = (
        plan.tinkoff_amount_rub_yearly
        if sub.billing_period == "year"
        else plan.tinkoff_amount_rub_monthly
    )
    if amount_rub is None:
        logger.error(
            "billing renewal skipped subscription_id=%s reason=missing_tinkoff_amount",
            sub.id,
        )
        return "skipped"

    amount_kopecks = int(Decimal(amount_rub) * Decimal(100))
    description = f"WaiComputer {plan.code.upper()} {sub.billing_period}"
    try:
        response = await provider.charge_rebill(
            rebill_id=sub.tinkoff_rebill_id or "",
            amount_kopecks=amount_kopecks,
            description=description,
            customer_email=user.email,
            user_id=str(user.id),
        )
        raw_status = response.get("Status")
        if not raw_status:
            raise RuntimeError("Tinkoff Charge returned no Status")
        status = str(raw_status)
        event = ProviderEvent(
            type=f"tinkoff.{status.lower()}",
            subscription_id_provider=str(response.get("OrderId") or ""),
            customer_id_provider=str(user.id),
            status=_normalize_status(status),
            raw={
                "order_id": str(response.get("OrderId") or ""),
                "status": status,
                "rebill_id": sub.tinkoff_rebill_id,
                "payment_id": str(response.get("PaymentId") or ""),
                "amount": response.get("Amount") or amount_kopecks,
                "plan_code": plan.code,
                "period": sub.billing_period,
                "promo_code_id": str(sub.promo_code_id) if sub.promo_code_id else None,
                "payload": response,
            },
        )
        await apply_tinkoff_event(db, event)
        return "charged"
    except Exception:
        sub.status = SubscriptionStatus.PAST_DUE.value
        sub.tinkoff_next_charge_at = None
        logger.exception("billing renewal failed subscription_id=%s", sub.id)
        # Tell the user the renewal failed so they can fix their card before
        # access lapses. Best-effort — never re-raise into the renewal loop.
        await send_payment_failed_email(user.email, locale=user.region)
        return "failed"


@celery_app.task(
    bind=True,
    name="app.tasks.billing_renewals.charge_due_tinkoff_renewals",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=300,
    time_limit=360,
)
def charge_due_tinkoff_renewals_task(self, *, limit: int = 50) -> dict[str, int]:
    logger.info(
        "billing renewal task started task_id=%s limit=%s",
        getattr(self.request, "id", None),
        limit,
    )
    result = asyncio.run(charge_due_tinkoff_renewals(limit=limit))
    logger.info(
        "billing renewal task finished task_id=%s result=%s",
        getattr(self.request, "id", None),
        result,
    )
    return result


async def send_due_renewal_reminders(
    *,
    db_session: AsyncSession | None = None,
) -> dict[str, int]:
    """Email a heads-up to T-Bank subscribers ~3 days before their next charge."""
    if db_session is not None:
        return await _send_due_renewal_reminders_in_session(db_session)
    async with get_db_context() as db:
        return await _send_due_renewal_reminders_in_session(db)


async def _send_due_renewal_reminders_in_session(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(days=RENEWAL_REMINDER_LEAD_DAYS)
    window_end = window_start + timedelta(days=1)
    rows = (
        await db.execute(
            select(Subscription, Plan, User)
            .join(Plan, Subscription.plan_id == Plan.id)
            .join(User, Subscription.user_id == User.id)
            .where(
                Subscription.provider == "tinkoff",
                Subscription.status == SubscriptionStatus.ACTIVE.value,
                Subscription.cancel_at_period_end.is_(False),
                Subscription.tinkoff_next_charge_at.is_not(None),
                Subscription.tinkoff_next_charge_at >= window_start,
                Subscription.tinkoff_next_charge_at < window_end,
            )
        )
    ).all()

    reminded = 0
    for sub, plan, user in rows:
        charge_at = sub.tinkoff_next_charge_at
        if charge_at is None:  # pragma: no cover - query already filters NULLs
            continue
        # One reminder per (subscription, charge date) — re-run safe.
        prior = (
            await db.execute(
                select(BillingEvent).where(
                    BillingEvent.subscription_id == sub.id,
                    BillingEvent.type == "renewal_reminder_sent",
                )
            )
        ).scalars().all()
        if any((e.payload or {}).get("charge_at") == charge_at.isoformat() for e in prior):
            continue
        amount_rub = (
            plan.tinkoff_amount_rub_yearly
            if sub.billing_period == "year"
            else plan.tinkoff_amount_rub_monthly
        )
        if amount_rub is None:  # pragma: no cover - pro plan always has a RUB price
            continue
        await send_renewal_reminder_email(
            user.email,
            amount=Decimal(amount_rub),
            currency="RUB",
            next_charge_at=charge_at,
            locale=user.region,
        )
        db.add(
            BillingEvent(
                subscription_id=sub.id,
                type="renewal_reminder_sent",
                payload={"charge_at": charge_at.isoformat()},
            )
        )
        reminded += 1

    return {"reminded": reminded}


@celery_app.task(
    bind=True,
    name="app.tasks.billing_renewals.send_due_renewal_reminders",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=300,
    time_limit=360,
)
def send_due_renewal_reminders_task(self) -> dict[str, int]:
    logger.info(
        "renewal reminder task started task_id=%s",
        getattr(self.request, "id", None),
    )
    result = asyncio.run(send_due_renewal_reminders())
    logger.info(
        "renewal reminder task finished task_id=%s result=%s",
        getattr(self.request, "id", None),
        result,
    )
    return result
