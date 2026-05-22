"""Internal admin endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Database
from app.billing.promo_codes import generate_promo_code, hash_promo_code, normalize_promo_code
from app.config import get_settings
from app.models.billing import BillingPeriod, BillingPromoCode, Plan

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminPromoCodeCreateRequest(BaseModel):
    code: str | None = Field(default=None, max_length=128)
    prefix: str = Field(default="WAI", min_length=1, max_length=16)
    plan: str = Field(default="pro", min_length=1, max_length=20)
    billing_period: BillingPeriod = BillingPeriod.MONTH
    duration_days: int = Field(ge=1, le=3650)
    max_redemptions: int = Field(ge=1, le=100_000)
    expires_days: int | None = Field(default=30, ge=1, le=3650)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("code", "note", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        normalized = normalize_promo_code(value)
        if not normalized:
            raise ValueError("prefix must contain letters or digits")
        return normalized

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not normalize_promo_code(value):
            raise ValueError("code must contain letters or digits")
        return value.strip().upper()

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AdminPromoCodeResponse(BaseModel):
    code: str
    normalized_code: str
    plan: str
    billing_period: str
    duration_days: int
    max_redemptions: int
    redeemed_count: int
    active: bool
    expires_at: datetime | None
    note: str | None


def require_admin_password(x_wai_admin_password: str | None) -> None:
    """Validate the internal admin password without storing or logging it."""
    configured = get_settings().admin_password
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin password is not configured",
        )
    supplied = x_wai_admin_password or ""
    if not secrets.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin password",
        )


@router.post("/promo-codes", response_model=AdminPromoCodeResponse)
async def create_admin_promo_code(
    payload: AdminPromoCodeCreateRequest,
    db: Database,
    x_wai_admin_password: Annotated[
        str | None, Header(alias="X-Wai-Admin-Password")
    ] = None,
) -> AdminPromoCodeResponse:
    """Create a hash-stored promo code and return the plaintext once."""
    require_admin_password(x_wai_admin_password)

    plan = (
        await db.execute(select(Plan).where(Plan.code == payload.plan))
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=400, detail="Billing plan not found")

    code = payload.code or generate_promo_code(prefix=payload.prefix)
    normalized = normalize_promo_code(code)
    code_hash = hash_promo_code(normalized)
    existing = (
        await db.execute(select(BillingPromoCode).where(BillingPromoCode.code_hash == code_hash))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Promo code already exists")

    expires_at = None
    if payload.expires_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_days)

    promo = BillingPromoCode(
        code_hash=code_hash,
        plan_id=plan.id,
        billing_period=payload.billing_period.value,
        duration_days=payload.duration_days,
        max_redemptions=payload.max_redemptions,
        expires_at=expires_at,
        note=payload.note,
    )
    db.add(promo)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Promo code already exists") from exc

    return AdminPromoCodeResponse(
        code=code,
        normalized_code=normalized,
        plan=plan.code,
        billing_period=promo.billing_period,
        duration_days=promo.duration_days,
        max_redemptions=promo.max_redemptions,
        redeemed_count=promo.redeemed_count,
        active=promo.active,
        expires_at=promo.expires_at,
        note=promo.note,
    )
