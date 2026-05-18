"""Billing API routes — usage, plans, subscription, checkout.

Checkout/cancel/webhook endpoints are scaffolded; the Stripe and T-Bank
providers fill them in (Phases 2 and 3 of the v1.0 sprint).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.billing.providers.base import ProviderUnavailableError
from app.billing.providers.stripe_provider import StripeProvider
from app.billing.providers.tinkoff_provider import TinkoffProvider
from app.billing.quota import WordQuota
from app.config import get_settings
from app.models.billing import (
    BillingPeriod,
    BillingProvider,
    Plan,
    Subscription,
)

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
    usd_amount_monthly: Decimal | None
    usd_amount_yearly: Decimal | None
    rub_amount_monthly: Decimal | None
    rub_amount_yearly: Decimal | None
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


class CheckoutRequest(BaseModel):
    plan: str  # plan code, e.g. "pro"
    period: str  # "month" | "year"
    provider: str | None = None  # optional override: "stripe" | "tinkoff"


@router.get("/usage", response_model=UsageResponse)
async def get_usage(user: CurrentUser, db: Database) -> UsageResponse:
    """Return this user's current weekly transcription usage."""
    result = await WordQuota.check(db, user, estimated_words=0)
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
async def get_subscription(user: CurrentUser, db: Database) -> SubscriptionResponse:
    """Return the user's effective subscription (active or free fallback)."""
    plan: Plan | None = None
    sub: Subscription | None = None
    if user.current_subscription_id is not None:
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.id == user.current_subscription_id)
            )
        ).scalar_one_or_none()
        if sub is not None:
            plan = (
                await db.execute(select(Plan).where(Plan.id == sub.plan_id))
            ).scalar_one_or_none()
    if plan is None:
        plan = (await db.execute(select(Plan).where(Plan.code == "free"))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Free plan missing"
        )

    plan_payload = PlanResponse(
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
    return SubscriptionResponse(
        plan=plan_payload,
        status=sub.status if sub is not None else "free",
        provider=sub.provider if sub is not None else None,
        billing_period=sub.billing_period if sub is not None else None,
        current_period_end=sub.current_period_end if sub is not None else None,
        cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
        trial_end=sub.trial_end if sub is not None else None,
    )


def _pick_provider(user_region: str, override: str | None) -> str:
    """Resolve which payment rail to use. Override > user.region > default."""
    if override:
        return override
    if user_region == "ru":
        return BillingProvider.TINKOFF.value
    return BillingProvider.STRIPE.value


class CheckoutResponse(BaseModel):
    provider: str
    checkout_url: str


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
    if payload.provider is not None and payload.provider not in {p.value for p in BillingProvider}:
        raise HTTPException(status_code=400, detail="Unknown provider")

    settings = get_settings()
    provider_code = _pick_provider(user.region, payload.provider)
    frontend = settings.frontend_url.rstrip("/")
    success_url = f"{frontend}/billing/success"
    cancel_url = f"{frontend}/billing/cancel"

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
                trial_days=settings.billing_trial_days,
            )
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Stripe not configured: {exc}",
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
            )
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"T-Bank not configured: {exc}",
            ) from exc
        return CheckoutResponse(provider=result.provider, checkout_url=result.checkout_url)

    raise HTTPException(status_code=400, detail="Unknown provider")


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
                detail=f"Stripe not configured: {exc}",
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
