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
from app.billing.quota import WordQuota
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


@router.post("/checkout", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_checkout(
    payload: CheckoutRequest,
    user: CurrentUser,
    db: Database,
) -> dict:
    """Create a checkout session — implemented by Stripe + T-Bank providers."""
    # Phase 2/3 fill this in. Validate inputs so callers get a useful 4xx.
    if payload.plan not in {"pro"}:
        raise HTTPException(status_code=400, detail="Unknown plan")
    if payload.period not in {p.value for p in BillingPeriod}:
        raise HTTPException(status_code=400, detail="Unknown period")
    if payload.provider is not None and payload.provider not in {p.value for p in BillingProvider}:
        raise HTTPException(status_code=400, detail="Unknown provider")
    raise HTTPException(status_code=501, detail="Checkout not yet wired")


@router.post("/cancel", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def cancel_subscription(user: CurrentUser, db: Database) -> dict:
    """Cancel at period end — implemented by Stripe + T-Bank providers."""
    raise HTTPException(status_code=501, detail="Cancel not yet wired")
