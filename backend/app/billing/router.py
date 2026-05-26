"""Billing API routes — usage, plans, subscription, checkout.

Checkout/cancel/webhook endpoints are scaffolded; the Stripe and T-Bank
providers fill them in (Phases 2 and 3 of the v1.0 sprint).
"""

from __future__ import annotations

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
from app.models.billing import (
    BillingPeriod,
    BillingPromoCode,
    BillingPromoRedemption,
    BillingProvider,
    Plan,
    Subscription,
    SubscriptionStatus,
)

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
    # When false, clients SHOULD hide the entire billing UI: word gauges,
    # upgrade buttons, plan badges. The backend will not return 402 in this
    # mode either, so quota checks become advisory.
    enforcement_enabled: bool


class CheckoutRequest(BaseModel):
    plan: str  # plan code, e.g. "pro"
    period: str  # "month" | "year"
    provider: str | None = None  # optional override: "stripe" | "tinkoff"
    promo_code: str | None = None


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
    """Resolve which payment rail to use. Override > user.region > default."""
    if override:
        return override
    if user_region == "ru":
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
            .where(BillingPromoCode.code_hash == hash_promo_code(normalized))
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


def _subscription_payload(
    *,
    plan: Plan,
    sub: Subscription | None,
    enforcement_enabled: bool,
) -> SubscriptionResponse:
    return SubscriptionResponse(
        plan=_plan_payload(plan),
        status=sub.status if sub is not None else "free",
        provider=sub.provider if sub is not None else None,
        billing_period=sub.billing_period if sub is not None else None,
        current_period_end=sub.current_period_end if sub is not None else None,
        cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
        trial_end=sub.trial_end if sub is not None else None,
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
        db.add(
            Subscription(
                user_id=user.id,
                plan_id=plan.id,
                status=SubscriptionStatus.INCOMPLETE.value,
                provider=BillingProvider.TINKOFF.value,
                billing_period=payload.period,
                promo_code_id=promo.id if promo is not None else None,
                tinkoff_order_id=result.provider_order_id,
                tinkoff_customer_key=str(user.id),
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
            .where(BillingPromoCode.code_hash == hash_promo_code(normalized))
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
