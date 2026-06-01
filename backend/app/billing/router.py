"""Billing API routes — usage, plans, subscription, checkout.

Checkout/cancel/webhook endpoints are scaffolded; the Stripe and T-Bank
providers fill them in (Phases 2 and 3 of the v1.0 sprint).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, PlainSerializer
from sqlalchemy import select

from app.api.deps import CurrentUser, Database, PaymentModeOverride
from app.billing.promo_codes import hash_promo_code, normalize_promo_code
from app.billing.providers.base import ProviderUnavailableError
from app.billing.providers.stripe_provider import StripeProvider
from app.billing.providers.tinkoff_provider import TinkoffProvider
from app.billing.quota import WordQuota
from app.billing.subscriptions import subscription_is_entitled
from app.config import get_settings
from app.core.observability import add_sentry_breadcrumb
from app.models.billing import (
    BillingEvent,
    BillingPeriod,
    BillingPromoCode,
    BillingPromoRedemption,
    BillingProvider,
    Invoice,
    Plan,
    Subscription,
    SubscriptionStatus,
)

logger = logging.getLogger(__name__)

# Decimal values land on the wire as JSON numbers, not strings. The Apple
# clients decode these straight into `Decimal`/`NSDecimal`, which rejects
# JSON strings with `typeMismatch`. Float is lossless for cent-level prices.
DecimalNumber = Annotated[
    Decimal | None,
    PlainSerializer(
        lambda v: float(v) if v is not None else None,
        return_type=float | None,
        when_used="json",
    ),
]

router = APIRouter(prefix="/billing", tags=["billing"])

# Version of the recurrent-payment agreement (separate from the general
# Terms/Privacy versions in auth.py). Bumped when the auto-renewal oferta text
# materially changes; recorded against each subscription's consent event so we
# can prove which terms the user accepted when T-Bank reviews the mandate.
LEGAL_SUBSCRIPTION_VERSION = "2026-06-01"


class UsageResponse(BaseModel):
    """Free-tier weekly usage status."""

    words_used: int
    words_cap: int | None
    reset_at: datetime
    cap_exceeded: bool


class PlanResponse(BaseModel):
    code: str
    name: str
    description: str | None
    usd_amount_monthly: DecimalNumber
    usd_amount_yearly: DecimalNumber
    rub_amount_monthly: DecimalNumber
    rub_amount_yearly: DecimalNumber
    word_cap_per_week: int | None
    memory_retention_days: int | None
    features: dict


class SubscriptionResponse(BaseModel):
    plan: PlanResponse
    status: str
    provider: str | None
    billing_period: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    trial_end: datetime | None
    # The dashboard's "Next charge $X on Mon DD" banner reads these.
    # `next_charge_at` falls back to `tinkoff_next_charge_at` for T-Bank and
    # `current_period_end` for Stripe (since `cancel_at_period_end` flips the
    # banner copy to "Ends" rather than charging again).
    next_charge_at: datetime | None
    next_charge_amount: DecimalNumber
    next_charge_currency: str | None
    # When false, clients SHOULD hide the entire billing UI: word gauges,
    # upgrade buttons, plan badges. The backend will not return 402 in this
    # mode either, so quota checks become advisory.
    enforcement_enabled: bool


class InvoiceResponse(BaseModel):
    """Single invoice row for the billing-page history table.

    Stripe-sourced rows fill ``hosted_invoice_url``/``invoice_pdf`` (the URLs
    Stripe hosts itself); local-mirror-only rows can still use ``receipt_url``
    for older T-Bank invoices. Frontend prefers ``hosted_invoice_url`` when
    both are present.
    """

    id: str
    amount: DecimalNumber
    currency: str
    status: str
    paid_at: datetime | None
    created_at: datetime
    receipt_url: str | None
    description: str | None
    hosted_invoice_url: str | None = None
    invoice_pdf: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None


class PortalResponse(BaseModel):
    """Stripe Customer Portal session URL.

    The frontend redirects via ``window.location.href = url`` so the user
    lands on Stripe-hosted pages for card updates and subscription management.
    """

    url: str


class SwitchPlanRequest(BaseModel):
    """Request body for `/api/billing/switch-plan`."""

    period: str  # "monthly" | "yearly" (loose match against BillingPeriod)


class SwitchPlanResponse(BaseModel):
    """Stub response after recording the user's intent to switch period."""

    status: str
    requested_period: str


class CheckoutRequest(BaseModel):
    plan: str  # plan code, e.g. "pro"
    period: str  # "month" | "year"
    provider: str | None = None  # optional override: "stripe" | "tinkoff"
    promo_code: str | None = None
    # T-Bank recurrent mandate: the RU checkout MUST gate the pay button on an
    # explicit, non-pre-checked consent to auto-renewal + personal-data
    # processing. Stripe issues its own receipts/mandate and is exempt.
    accepted_recurring_terms: bool = False


class PromoClaimRequest(BaseModel):
    code: str


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    user: CurrentUser, db: Database, enforce_payment: PaymentModeOverride
) -> UsageResponse:
    """Return this user's current weekly transcription usage.

    Respects the per-request Payment-mode override so a tester sees their
    real cap state while everyone else stays in uncapped compatibility mode.
    """
    result = await WordQuota.check(
        db, user, estimated_words=0, enforce_override=enforce_payment
    )
    return UsageResponse(
        words_used=result.words_used,
        words_cap=result.words_cap,
        reset_at=result.reset_at,
        cap_exceeded=result.cap_exceeded,
    )


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: Database) -> list[PlanResponse]:
    """Return all advertised billing plans."""
    stmt = select(Plan).order_by(Plan.usd_amount_monthly.nulls_first())
    rows = (await db.execute(stmt)).scalars()
    return [
        PlanResponse(
            code=p.code,
            name=p.name,
            description=p.description,
            usd_amount_monthly=p.usd_amount_monthly,
            usd_amount_yearly=p.usd_amount_yearly,
            rub_amount_monthly=p.tinkoff_amount_rub_monthly,
            rub_amount_yearly=p.tinkoff_amount_rub_yearly,
            word_cap_per_week=p.word_cap_per_week,
            memory_retention_days=p.memory_retention_days,
            features=p.features or {},
        )
        for p in rows
    ]


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    user: CurrentUser, db: Database, enforce_payment: PaymentModeOverride
) -> SubscriptionResponse:
    """Return the user's effective subscription (active or free fallback)."""
    plan: Plan | None = None
    sub: Subscription | None = None
    if user.current_subscription_id is not None:
        candidate_sub = (
            await db.execute(
                select(Subscription).where(Subscription.id == user.current_subscription_id)
            )
        ).scalar_one_or_none()
        if candidate_sub is not None and subscription_is_entitled(candidate_sub):
            sub = candidate_sub
            plan = (
                await db.execute(select(Plan).where(Plan.id == sub.plan_id))
            ).scalar_one_or_none()
    if plan is None:
        plan = (await db.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Free plan missing"
        )

    settings = get_settings()
    return _subscription_payload(
        plan=plan,
        sub=sub,
        enforcement_enabled=settings.billing_enforcement_enabled or enforce_payment,
    )


def _pick_provider(user_region: str, override: str | None) -> str:
    """Resolve which payment rail to use. Override > user.region > default.

    The ``ru`` region maps to the T-Bank rail; everything else (and a missing
    region) falls back to ``billing_default_region`` — ``ru`` there would route
    region-less users to T-Bank, otherwise Stripe.
    """
    if override:
        return override
    region = user_region or get_settings().billing_default_region
    if region == "ru":
        return BillingProvider.TINKOFF.value
    return BillingProvider.STRIPE.value


def _checkout_result_urls(frontend_url: str, provider_code: str) -> tuple[str, str]:
    frontend = frontend_url.rstrip("/")
    if provider_code == BillingProvider.TINKOFF.value:
        query = urlencode({"provider": BillingProvider.TINKOFF.value, "lang": "ru"})
        return f"{frontend}/billing/success?{query}", f"{frontend}/billing/cancel?{query}"
    return f"{frontend}/billing/success", f"{frontend}/billing/cancel"


class CheckoutResponse(BaseModel):
    provider: str
    checkout_url: str


def _promo_expired(promo: BillingPromoCode, now: datetime) -> bool:
    expires_at = promo.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at is not None and expires_at <= now


async def _checkout_discount_promo(
    *,
    db: Database,
    user: CurrentUser,
    promo_code: str | None,
    period: str,
) -> BillingPromoCode | None:
    if promo_code is None or not promo_code.strip():
        return None
    normalized = normalize_promo_code(promo_code)
    if not normalized:
        raise HTTPException(status_code=404, detail="Promo code not found")
    promo = (
        await db.execute(
            select(BillingPromoCode)
            .where(
                BillingPromoCode.code_hash == hash_promo_code(normalized),
                BillingPromoCode.archived_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if promo is None or not promo.active:
        raise HTTPException(status_code=404, detail="Promo code not found")
    if promo.promotion_type != "discount":
        raise HTTPException(status_code=400, detail="Promo code grants Pro access")
    if _promo_expired(promo, datetime.now(timezone.utc)):
        raise HTTPException(status_code=400, detail="Promo code expired")
    if promo.redeemed_count >= promo.max_redemptions:
        raise HTTPException(status_code=409, detail="Promo code exhausted")
    if promo.billing_period != period:
        raise HTTPException(status_code=400, detail="Promo code does not apply to selected period")
    existing_redemption = (
        await db.execute(
            select(BillingPromoRedemption).where(
                BillingPromoRedemption.promo_code_id == promo.id,
                BillingPromoRedemption.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing_redemption is not None:
        raise HTTPException(status_code=409, detail="Promo code already redeemed")
    if promo.discount_percent is None:
        raise HTTPException(status_code=500, detail="Promo code discount missing")
    return promo


def _plan_payload(plan: Plan) -> PlanResponse:
    return PlanResponse(
        code=plan.code,
        name=plan.name,
        description=plan.description,
        usd_amount_monthly=plan.usd_amount_monthly,
        usd_amount_yearly=plan.usd_amount_yearly,
        rub_amount_monthly=plan.tinkoff_amount_rub_monthly,
        rub_amount_yearly=plan.tinkoff_amount_rub_yearly,
        word_cap_per_week=plan.word_cap_per_week,
        memory_retention_days=plan.memory_retention_days,
        features=plan.features or {},
    )


def _next_charge_for(plan: Plan, sub: Subscription | None) -> tuple[
    datetime | None, Decimal | None, str | None
]:
    """Resolve when the user is next charged, how much, and in what currency.

    Returns (None, None, None) when there is no upcoming charge — either no
    paid subscription, or `cancel_at_period_end=True` (subscription will end
    rather than renew).
    """
    if sub is None or sub.cancel_at_period_end:
        return None, None, None
    period = sub.billing_period
    if sub.provider == BillingProvider.TINKOFF.value:
        amount = (
            plan.tinkoff_amount_rub_yearly
            if period == BillingPeriod.YEAR.value
            else plan.tinkoff_amount_rub_monthly
        )
        next_at = sub.tinkoff_next_charge_at or sub.current_period_end
        return next_at, amount, "RUB"
    if sub.provider == BillingProvider.STRIPE.value:
        amount = (
            plan.usd_amount_yearly
            if period == BillingPeriod.YEAR.value
            else plan.usd_amount_monthly
        )
        return sub.current_period_end, amount, "USD"
    if sub.provider == BillingProvider.PROMO.value:
        # Promo grants do not renew; surface period_end so the UI can say
        # "Pro is active through …" instead of "Next charge".
        return None, None, None
    return sub.current_period_end, None, None


def _subscription_payload(
    *,
    plan: Plan,
    sub: Subscription | None,
    enforcement_enabled: bool,
) -> SubscriptionResponse:
    next_at, next_amount, next_currency = _next_charge_for(plan, sub)
    return SubscriptionResponse(
        plan=_plan_payload(plan),
        status=sub.status if sub is not None else "free",
        provider=sub.provider if sub is not None else None,
        billing_period=sub.billing_period if sub is not None else None,
        current_period_end=sub.current_period_end if sub is not None else None,
        cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
        trial_end=sub.trial_end if sub is not None else None,
        next_charge_at=next_at,
        next_charge_amount=next_amount,
        next_charge_currency=next_currency,
        enforcement_enabled=enforcement_enabled,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    payload: CheckoutRequest,
    user: CurrentUser,
    db: Database,
) -> CheckoutResponse:
    """Create a hosted checkout session and return its URL."""
    if payload.plan not in {"pro"}:
        raise HTTPException(status_code=400, detail="Unknown plan")
    if payload.period not in {p.value for p in BillingPeriod}:
        raise HTTPException(status_code=400, detail="Unknown period")
    checkout_providers = {BillingProvider.STRIPE.value, BillingProvider.TINKOFF.value}
    if payload.provider is not None and payload.provider not in checkout_providers:
        raise HTTPException(status_code=400, detail="Unknown provider")

    settings = get_settings()
    provider_code = _pick_provider(user.region, payload.provider)
    # The T-Bank rail is RU-only: enforce it server-side so a non-RU user can't
    # land on the recurrent Charge mandate by overriding `provider=tinkoff`
    # (the RU-scoped compliance UX would never have been shown to them).
    if provider_code == BillingProvider.TINKOFF.value:
        if user.region != "ru":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="T-Bank checkout is only available in the RU region",
            )
        if not payload.accepted_recurring_terms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recurring payment consent is required",
            )
    success_url, cancel_url = _checkout_result_urls(settings.frontend_url, provider_code)
    promo = await _checkout_discount_promo(
        db=db,
        user=user,
        promo_code=payload.promo_code,
        period=payload.period,
    )

    if provider_code == BillingProvider.STRIPE.value:
        provider = StripeProvider()
        try:
            result = await provider.create_checkout(
                plan_code=payload.plan,
                period=payload.period,
                user_email=user.email,
                user_id=str(user.id),
                success_url=success_url,
                cancel_url=cancel_url,
                trial_days=None,
                discount_percent=promo.discount_percent if promo is not None else None,
                discount_code=promo.code if promo is not None else None,
                promo_code_id=str(promo.id) if promo is not None else None,
            )
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Stripe checkout unavailable: {exc}",
            ) from exc
        return CheckoutResponse(provider=result.provider, checkout_url=result.checkout_url)

    if provider_code == BillingProvider.TINKOFF.value:
        provider = TinkoffProvider()
        try:
            result = await provider.create_checkout(
                plan_code=payload.plan,
                period=payload.period,
                user_email=user.email,
                user_id=str(user.id),
                success_url=success_url,
                cancel_url=cancel_url,
                trial_days=None,  # T-Bank Init has no native trial; first charge is real.
                discount_percent=promo.discount_percent if promo is not None else None,
                discount_code=promo.code if promo is not None else None,
                promo_code_id=str(promo.id) if promo is not None else None,
            )
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"T-Bank checkout unavailable: {exc}",
            ) from exc
        if not result.provider_order_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="T-Bank checkout unavailable: Init returned no OrderId",
            )
        plan = (
            await db.execute(select(Plan).where(Plan.code == payload.plan))
        ).scalar_one_or_none()
        if plan is None:
            raise HTTPException(status_code=400, detail="Unknown plan")
        amount_rub = (
            plan.tinkoff_amount_rub_yearly
            if payload.period == BillingPeriod.YEAR.value
            else plan.tinkoff_amount_rub_monthly
        )
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.INCOMPLETE.value,
            provider=BillingProvider.TINKOFF.value,
            billing_period=payload.period,
            promo_code_id=promo.id if promo is not None else None,
            tinkoff_order_id=result.provider_order_id,
            tinkoff_customer_key=str(user.id),
        )
        db.add(sub)
        await db.flush()
        # Durable proof of the recurrent-payment + personal-data consent the
        # user gave at checkout. T-Bank's recurrent review requires the user to
        # have actively accepted auto-renewal terms; we keep the version +
        # amount + period so support can show exactly what was agreed.
        db.add(
            BillingEvent(
                subscription_id=sub.id,
                type="recurrent_consent_accepted",
                payload={
                    "version": LEGAL_SUBSCRIPTION_VERSION,
                    "plan": payload.plan,
                    "period": payload.period,
                    "amount_rub": float(amount_rub) if amount_rub is not None else None,
                    "locale": "ru",
                    "accepted_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        return CheckoutResponse(provider=result.provider, checkout_url=result.checkout_url)

    raise HTTPException(status_code=400, detail="Unknown provider")


@router.post("/promo/claim", response_model=SubscriptionResponse)
async def claim_promo_code(
    payload: PromoClaimRequest,
    user: CurrentUser,
    db: Database,
    enforce_payment: PaymentModeOverride,
) -> SubscriptionResponse:
    """Redeem a hash-stored promo code for non-renewing Pro access."""
    normalized = normalize_promo_code(payload.code)
    if not normalized:
        raise HTTPException(status_code=404, detail="Promo code not found")

    promo = (
        await db.execute(
            select(BillingPromoCode)
            .where(
                BillingPromoCode.code_hash == hash_promo_code(normalized),
                BillingPromoCode.archived_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if promo is None or not promo.active:
        raise HTTPException(status_code=404, detail="Promo code not found")
    if promo.promotion_type != "access":
        raise HTTPException(status_code=400, detail="Promo code applies to checkout")

    now = datetime.now(timezone.utc)
    if _promo_expired(promo, now):
        raise HTTPException(status_code=400, detail="Promo code expired")
    if promo.redeemed_count >= promo.max_redemptions:
        raise HTTPException(status_code=409, detail="Promo code exhausted")

    existing_redemption = (
        await db.execute(
            select(BillingPromoRedemption).where(
                BillingPromoRedemption.promo_code_id == promo.id,
                BillingPromoRedemption.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing_redemption is not None:
        raise HTTPException(status_code=409, detail="Promo code already redeemed")

    plan = (await db.execute(select(Plan).where(Plan.id == promo.plan_id))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=500, detail="Promo code plan missing")
    if promo.duration_days is None:
        raise HTTPException(status_code=500, detail="Promo code duration missing")

    if user.current_subscription_id is not None:
        current_sub = (
            await db.execute(
                select(Subscription).where(Subscription.id == user.current_subscription_id)
            )
        ).scalar_one_or_none()
        if current_sub is not None and subscription_is_entitled(current_sub):
            raise HTTPException(status_code=409, detail="Active subscription already exists")

    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE.value,
        provider=BillingProvider.PROMO.value,
        billing_period=promo.billing_period,
        current_period_start=now,
        current_period_end=now + timedelta(days=promo.duration_days),
        cancel_at_period_end=True,
    )
    db.add(sub)
    await db.flush()
    db.add(
        BillingPromoRedemption(
            promo_code_id=promo.id,
            user_id=user.id,
            subscription_id=sub.id,
        )
    )
    promo.redeemed_count += 1
    user.current_subscription_id = sub.id
    await db.flush()

    settings = get_settings()
    return _subscription_payload(
        plan=plan,
        sub=sub,
        enforcement_enabled=settings.billing_enforcement_enabled or enforce_payment,
    )


@router.post("/cancel")
async def cancel_subscription(user: CurrentUser, db: Database) -> dict:
    """Cancel the user's active subscription at period end."""
    if user.current_subscription_id is None:
        raise HTTPException(status_code=400, detail="No active subscription")
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.id == user.current_subscription_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=400, detail="No active subscription")

    if sub.provider == BillingProvider.STRIPE.value and sub.stripe_subscription_id:
        provider = StripeProvider()
        try:
            await provider.cancel_subscription(sub.stripe_subscription_id)
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Stripe subscription unavailable: {exc}",
            ) from exc
        sub.cancel_at_period_end = True
        await db.flush()
        return {"cancel_at_period_end": True}

    if sub.provider == BillingProvider.TINKOFF.value:
        # T-Bank has no native subscription-cancel API. Flip the local flag and
        # the rebill scheduler will stop charging on the next cycle.
        sub.cancel_at_period_end = True
        await db.flush()
        return {"cancel_at_period_end": True}

    raise HTTPException(status_code=400, detail="Unknown provider on subscription")


def _ts_to_datetime(value: object) -> datetime | None:
    """Stripe returns seconds-since-epoch ints; coerce to aware UTC datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _stripe_invoice_to_response(inv: dict) -> InvoiceResponse | None:
    """Map a Stripe Invoice dict into our wire shape. Returns None on bad data."""
    invoice_id = inv.get("id")
    created = _ts_to_datetime(inv.get("created"))
    if not invoice_id or created is None:
        return None
    amount_cents = inv.get("amount_paid")
    if amount_cents in (None, 0):
        amount_cents = inv.get("amount_due") or 0
    amount = Decimal(int(amount_cents)) / Decimal(100)
    paid_at_ts = inv.get("status_transitions", {}).get("paid_at") if isinstance(
        inv.get("status_transitions"), dict
    ) else None
    period_start = None
    period_end = None
    # Stripe puts period info on each line item; fall back to the top-level
    # period field if it's present.
    lines = inv.get("lines", {})
    if isinstance(lines, dict):
        data = lines.get("data") or []
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                period = first.get("period") if isinstance(first.get("period"), dict) else None
                if isinstance(period, dict):
                    period_start = _ts_to_datetime(period.get("start"))
                    period_end = _ts_to_datetime(period.get("end"))
    if period_start is None and isinstance(inv.get("period_start"), int):
        period_start = _ts_to_datetime(inv.get("period_start"))
    if period_end is None and isinstance(inv.get("period_end"), int):
        period_end = _ts_to_datetime(inv.get("period_end"))
    hosted_url = inv.get("hosted_invoice_url")
    return InvoiceResponse(
        id=str(invoice_id),
        amount=amount,
        currency=(inv.get("currency") or "usd").upper(),
        status=str(inv.get("status") or "open"),
        paid_at=_ts_to_datetime(paid_at_ts),
        created_at=created,
        # Keep `receipt_url` populated for back-compat (older clients that
        # only know about that field).
        receipt_url=hosted_url,
        description=inv.get("description"),
        hosted_invoice_url=hosted_url,
        invoice_pdf=inv.get("invoice_pdf"),
        period_start=period_start,
        period_end=period_end,
    )


def _local_invoice_to_response(row: Invoice) -> InvoiceResponse:
    return InvoiceResponse(
        id=str(row.id),
        amount=row.amount,
        currency=(row.currency or "USD").upper(),
        status=row.status,
        paid_at=row.paid_at,
        created_at=row.created_at,
        receipt_url=row.receipt_url,
        description=None,
        hosted_invoice_url=row.receipt_url,
        invoice_pdf=None,
        period_start=None,
        period_end=None,
    )


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(user: CurrentUser, db: Database) -> list[InvoiceResponse]:
    """Return the user's invoice history, newest first.

    Stripe is the source of truth for Stripe-rail invoices (hosted PDF + URL),
    so when a ``stripe_customer_id`` is set we fetch live from Stripe and
    merge with our local mirror — Stripe wins on id collisions because their
    payload also carries ``hosted_invoice_url``/``invoice_pdf`` which we
    don't always persist locally.
    """
    stmt = (
        select(Invoice)
        .join(Subscription, Subscription.id == Invoice.subscription_id)
        .where(Subscription.user_id == user.id)
        .order_by(Invoice.created_at.desc())
        .limit(25)
    )
    local_rows = (await db.execute(stmt)).scalars().all()

    if not user.stripe_customer_id:
        return [_local_invoice_to_response(row) for row in local_rows]

    provider = StripeProvider()
    try:
        stripe_rows = await provider.list_customer_invoices(
            customer_id=user.stripe_customer_id, limit=25
        )
    except ProviderUnavailableError:
        # Stripe not configured in this env — fall back to local mirror.
        return [_local_invoice_to_response(row) for row in local_rows]
    except Exception as exc:  # noqa: BLE001 — Stripe SDK raises stripe.error.*
        logger.warning("Stripe invoice list failed: %s", exc)
        add_sentry_breadcrumb(
            category="billing.stripe",
            message="stripe.Invoice.list failed",
            data={"reason": type(exc).__name__},
            level="warning",
        )
        return [_local_invoice_to_response(row) for row in local_rows]

    # Build a dict keyed by Stripe invoice id; local rows that share that id
    # (via provider_payment_id) defer to Stripe.
    merged: dict[str, InvoiceResponse] = {}
    stripe_ids: set[str] = set()
    for raw in stripe_rows:
        item = _stripe_invoice_to_response(raw)
        if item is None:
            continue
        merged[item.id] = item
        stripe_ids.add(item.id)
    for row in local_rows:
        payment_id = row.provider_payment_id
        if payment_id and payment_id in stripe_ids:
            continue
        merged[str(row.id)] = _local_invoice_to_response(row)

    ordered = sorted(
        merged.values(),
        key=lambda i: i.created_at,
        reverse=True,
    )
    return ordered[:25]


@router.post("/portal", response_model=PortalResponse)
async def open_billing_portal(user: CurrentUser, db: Database) -> PortalResponse:
    """Create a Stripe Billing Portal session for the current user.

    The portal lets the user update their card, cancel/resume the
    subscription, and download invoices on Stripe-hosted pages — no card
    data ever touches our backend. If the user has never been a Stripe
    customer (e.g. they got Pro via a promo code), we lazily create the
    customer using their email and persist the id.
    """
    settings = get_settings()
    provider = StripeProvider()
    return_url = f"{settings.frontend_url.rstrip('/')}/billing"

    customer_id = user.stripe_customer_id
    if not customer_id:
        try:
            customer_id = await provider.ensure_customer(
                user_id=str(user.id), email=user.email
            )
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Stripe portal unavailable: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            add_sentry_breadcrumb(
                category="billing.stripe",
                message="stripe.Customer.create failed",
                data={"reason": type(exc).__name__},
                level="error",
            )
            logger.warning("Stripe customer create failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Stripe portal unavailable",
            ) from exc
        user.stripe_customer_id = customer_id
        await db.flush()

    try:
        url = await provider.create_portal_session(
            customer_id=customer_id, return_url=return_url
        )
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Stripe portal unavailable: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — stripe.error.* hierarchy
        add_sentry_breadcrumb(
            category="billing.stripe",
            message="stripe.billing_portal.Session.create failed",
            data={"reason": type(exc).__name__},
            level="error",
        )
        logger.warning("Stripe portal session create failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe portal unavailable",
        ) from exc

    return PortalResponse(url=url)


@router.post(
    "/switch-plan",
    response_model=SwitchPlanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def switch_plan(
    payload: SwitchPlanRequest,
    user: CurrentUser,
    db: Database,
) -> SwitchPlanResponse:
    """Record the user's intent to switch billing period.

    This is a stub: Stripe / T-Bank Recurrent both need a follow-up call to
    update the active subscription, which is out of scope for this sprint.
    For now we log the intent in `billing_events` so support can act on it,
    and return 202 to acknowledge the request.
    """
    if user.current_subscription_id is None:
        raise HTTPException(status_code=400, detail="No active subscription")
    sub = (
        await db.execute(
            select(Subscription).where(Subscription.id == user.current_subscription_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=400, detail="No active subscription")

    raw_period = (payload.period or "").strip().lower()
    if raw_period in {"monthly", "month"}:
        period = BillingPeriod.MONTH.value
    elif raw_period in {"yearly", "annual", "year"}:
        period = BillingPeriod.YEAR.value
    else:
        raise HTTPException(status_code=400, detail="Unknown period")

    db.add(
        BillingEvent(
            subscription_id=sub.id,
            type="switch_plan_requested",
            payload={
                "requested_period": period,
                "current_period": sub.billing_period,
                "user_id": str(user.id),
            },
        )
    )
    await db.flush()
    return SwitchPlanResponse(status="accepted", requested_period=period)
