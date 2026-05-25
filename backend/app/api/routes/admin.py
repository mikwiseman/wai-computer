"""Internal admin console endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, case, desc, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, Database
from app.billing.promo_codes import generate_promo_code, hash_promo_code, normalize_promo_code
from app.billing.providers.stripe_provider import StripeProvider
from app.billing.providers.tinkoff_provider import TinkoffProvider
from app.config import get_settings
from app.core.observability import get_release_version, get_sentry_runtime
from app.models.admin import AdminAuditLog, AdminRole, StaffMember
from app.models.api_key import ApiKey
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
    UsageWeek,
)
from app.models.dictation import DictationEntry
from app.models.mcp_oauth import McpOAuthToken
from app.models.recording import Recording, Segment
from app.models.refresh_token import RefreshToken
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_ROLES = {"owner", "admin", "support"}
ACCOUNT_STATUSES = {"active", "paused", "deactivated"}


class AdminPrincipal(BaseModel):
    user: User
    staff_member: StaffMember
    role: str

    model_config = {"arbitrary_types_allowed": True}


async def require_admin(user: CurrentUser, db: Database) -> AdminPrincipal:
    role_priority = case(
        (AdminRole.role == "owner", 0),
        (AdminRole.role == "admin", 1),
        (AdminRole.role == "support", 2),
        else_=99,
    )
    row = (
        await db.execute(
            select(AdminRole, StaffMember)
            .join(StaffMember, StaffMember.id == AdminRole.staff_member_id)
            .where(
                StaffMember.user_id == user.id,
                StaffMember.status == "active",
                AdminRole.revoked_at.is_(None),
                AdminRole.role.in_(ADMIN_ROLES),
            )
            .order_by(role_priority.asc(), AdminRole.created_at.asc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    role, staff_member = row
    return AdminPrincipal(user=user, staff_member=staff_member, role=role.role)


CurrentAdmin = Annotated[AdminPrincipal, Depends(require_admin)]


def _staff_user_ids_query():
    return select(StaffMember.user_id)


def _customer_user_filter():
    return User.id.not_in(_staff_user_ids_query())


async def _audit(
    db: Database,
    admin: AdminPrincipal,
    *,
    action: str,
    target_type: str,
    target_id: str | None,
    reason: str | None = None,
    details: dict | None = None,
    subscription_id: UUID | None = None,
) -> None:
    payload = {
        "actor_staff_member_id": str(admin.staff_member.id),
        "actor_user_id": str(admin.user.id),
        "actor_role": admin.role,
        "target_type": target_type,
        "target_id": target_id,
        **(details or {}),
    }
    db.add(
        AdminAuditLog(
            actor_staff_member_id=admin.staff_member.id,
            actor_user_id=admin.user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            details=payload,
        )
    )
    db.add(
        BillingEvent(
            subscription_id=subscription_id,
            type=f"admin.{action}",
            payload=payload,
        )
    )
    await db.flush()


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


class AdminPromoCodePatchRequest(BaseModel):
    active: bool | None = None
    expires_at: datetime | None = None
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    max_redemptions: int | None = Field(default=None, ge=1, le=100_000)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class PromoRedemptionResponse(BaseModel):
    user_id: str
    user_email: str
    subscription_id: str
    redeemed_at: datetime


class AdminPromoCodeResponse(BaseModel):
    id: str
    code: str | None = None
    normalized_code: str | None = None
    plan: str
    billing_period: str
    duration_days: int
    max_redemptions: int
    redeemed_count: int
    redemption_rate: float
    active: bool
    archived_at: datetime | None
    expires_at: datetime | None
    note: str | None
    created_at: datetime
    redemptions: list[PromoRedemptionResponse] = Field(default_factory=list)


class AdminPromoCodeListResponse(BaseModel):
    items: list[AdminPromoCodeResponse]


class AdminUserSummary(BaseModel):
    id: str
    email: str
    account_status: str
    account_status_reason: str | None
    created_at: datetime
    current_plan: str
    current_subscription_status: str | None
    current_subscription_provider: str | None
    dictation_words: int
    recording_words: int
    recording_count: int


class AdminUserListResponse(BaseModel):
    items: list[AdminUserSummary]


class AdminUserDetail(AdminUserSummary):
    subscriptions: list[dict]
    promo_redemptions: list[dict]
    weekly_usage: list[dict]


class AdminUserStatusPatchRequest(BaseModel):
    status: Literal["active", "paused", "deactivated"]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AdminGrantSubscriptionRequest(BaseModel):
    duration_days: int = Field(ge=1, le=3650)
    reason: str | None = Field(default=None, max_length=500)


class AdminSubscriptionResponse(BaseModel):
    id: str
    user_id: str
    plan: str
    status: str
    provider: str
    billing_period: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class AdminSubscriptionActionRequest(BaseModel):
    mode: Literal["period_end", "immediate"] = "period_end"
    reason: str | None = Field(default=None, max_length=500)


class AdminReasonRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AdminRefundRequest(BaseModel):
    amount_minor: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=80)


class AdminStatsResponse(BaseModel):
    users: dict
    promo: dict
    usage: dict
    billing: dict


class AdminObservabilityResponse(BaseModel):
    generated_at: datetime
    server: dict
    sentry: dict
    recording_pipeline: dict
    alerts: list[dict]


class AdminBillingInvoiceResponse(BaseModel):
    id: str
    amount: float
    currency: str
    status: str
    provider_payment_id: str | None
    paid_at: datetime | None
    created_at: datetime


class AdminBillingSubscriptionListItem(BaseModel):
    id: str
    user_id: str
    user_email: str
    plan: str
    status: str
    provider: str
    billing_period: str
    current_period_end: datetime | None
    cancel_at_period_end: bool
    invoices: list[AdminBillingInvoiceResponse]


class AdminBillingListResponse(BaseModel):
    items: list[AdminBillingSubscriptionListItem]


def _bucket_label(bucket: datetime, grain: Literal["month", "year"]) -> str:
    if grain == "year":
        return f"{bucket.year:04d}"
    return f"{bucket.year:04d}-{bucket.month:02d}"


def _usage_bucket(period: str) -> dict:
    return {
        "period": period,
        "recording_words": 0,
        "dictation_words": 0,
        "total_words": 0,
        "recording_duration_seconds": 0,
        "dictation_duration_seconds": 0.0,
        "recording_count": 0,
        "failed_recordings": 0,
    }


def _utc_date_trunc(grain: Literal["month", "year"], value):
    return func.date_trunc(grain, func.timezone("UTC", value))


async def _usage_buckets(
    db: Database,
    *,
    grain: Literal["month", "year"],
    since: datetime | None,
) -> list[dict]:
    buckets: dict[str, dict] = {}

    recording_bucket = _utc_date_trunc(grain, Recording.created_at)
    recording_query = select(
        recording_bucket.label("bucket"),
        func.coalesce(func.sum(Recording.billed_word_count), 0),
        func.coalesce(func.sum(Recording.duration_seconds), 0),
        func.count(Recording.id),
        func.coalesce(
            func.sum(case((Recording.status == "failed", 1), else_=0)),
            0,
        ),
    ).where(Recording.user_id.not_in(_staff_user_ids_query()))
    if since is not None:
        recording_query = recording_query.where(Recording.created_at >= since)
    recording_rows = (
        await db.execute(recording_query.group_by(recording_bucket).order_by(recording_bucket))
    ).all()
    for bucket, words, duration, count, failed in recording_rows:
        label = _bucket_label(bucket, grain)
        item = buckets.setdefault(label, _usage_bucket(label))
        item["recording_words"] = int(words or 0)
        item["recording_duration_seconds"] = int(duration or 0)
        item["recording_count"] = int(count or 0)
        item["failed_recordings"] = int(failed or 0)

    dictation_bucket = _utc_date_trunc(grain, DictationEntry.occurred_at)
    dictation_query = select(
        dictation_bucket.label("bucket"),
        func.coalesce(func.sum(DictationEntry.word_count), 0),
        func.coalesce(func.sum(DictationEntry.duration_seconds), 0),
    ).where(DictationEntry.user_id.not_in(_staff_user_ids_query()))
    if since is not None:
        dictation_query = dictation_query.where(DictationEntry.occurred_at >= since)
    dictation_rows = (
        await db.execute(dictation_query.group_by(dictation_bucket).order_by(dictation_bucket))
    ).all()
    for bucket, words, duration in dictation_rows:
        label = _bucket_label(bucket, grain)
        item = buckets.setdefault(label, _usage_bucket(label))
        item["dictation_words"] = int(words or 0)
        item["dictation_duration_seconds"] = float(duration or 0)

    for item in buckets.values():
        item["total_words"] = item["recording_words"] + item["dictation_words"]
    return [buckets[label] for label in sorted(buckets)]


async def _monthly_revenue(db: Database, *, since: datetime) -> list[dict]:
    bucket = _utc_date_trunc("month", Invoice.paid_at)
    rows = (
        await db.execute(
            select(
                bucket.label("bucket"),
                Invoice.currency,
                func.coalesce(func.sum(Invoice.amount), 0),
            )
            .join(Subscription, Subscription.id == Invoice.subscription_id)
            .where(
                Subscription.user_id.not_in(_staff_user_ids_query()),
                Invoice.status == "paid",
                Invoice.paid_at.is_not(None),
                Invoice.paid_at >= since,
            )
            .group_by(bucket, Invoice.currency)
            .order_by(bucket, Invoice.currency)
        )
    ).all()
    return [
        {
            "period": _bucket_label(month, "month"),
            "currency": currency,
            "amount": float(amount or 0),
        }
        for month, currency, amount in rows
    ]


async def _monthly_promo_redemptions(db: Database, *, since: datetime) -> list[dict]:
    bucket = _utc_date_trunc("month", BillingPromoRedemption.created_at)
    rows = (
        await db.execute(
            select(bucket.label("bucket"), func.count(BillingPromoRedemption.id))
            .where(
                BillingPromoRedemption.user_id.not_in(_staff_user_ids_query()),
                BillingPromoRedemption.created_at >= since,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()
    return [
        {"period": _bucket_label(month, "month"), "redemptions": int(count)}
        for month, count in rows
    ]


async def _recording_pipeline_observability(db: Database, *, now: datetime) -> dict:
    settings = get_settings()
    since = now - timedelta(hours=24)
    stale_before = now - timedelta(minutes=settings.recording_processing_stale_after_minutes)

    status_counts = dict(
        (status_value, int(count))
        for status_value, count in (
            await db.execute(
                select(Recording.status, func.count(Recording.id))
                .where(
                    Recording.deleted_at.is_(None),
                    Recording.user_id.not_in(_staff_user_ids_query()),
                )
                .group_by(Recording.status)
            )
        ).all()
    )
    last_24h_counts = dict(
        (status_value, int(count))
        for status_value, count in (
            await db.execute(
                select(Recording.status, func.count(Recording.id))
                .where(
                    Recording.deleted_at.is_(None),
                    Recording.user_id.not_in(_staff_user_ids_query()),
                    Recording.created_at >= since,
                )
                .group_by(Recording.status)
            )
        ).all()
    )
    last_24h_total = sum(last_24h_counts.values())
    failed_rate = (
        last_24h_counts.get("failed", 0) / last_24h_total if last_24h_total > 0 else 0.0
    )
    stuck_processing_count = int(
        (
            await db.execute(
                select(func.count(Recording.id)).where(
                    Recording.deleted_at.is_(None),
                    Recording.user_id.not_in(_staff_user_ids_query()),
                    Recording.status == "processing",
                    Recording.updated_at <= stale_before,
                )
            )
        ).scalar_one()
    )
    max_segment_end = (
        select(Segment.recording_id, func.max(Segment.end_ms).label("max_end_ms"))
        .group_by(Segment.recording_id)
        .subquery()
    )
    coverage_rows = (
        await db.execute(
            select(
                Recording.id,
                Recording.duration_seconds,
                max_segment_end.c.max_end_ms,
            )
            .outerjoin(max_segment_end, max_segment_end.c.recording_id == Recording.id)
            .where(
                Recording.deleted_at.is_(None),
                Recording.user_id.not_in(_staff_user_ids_query()),
                Recording.status == "ready",
                Recording.created_at >= since,
                Recording.duration_seconds.is_not(None),
                Recording.duration_seconds > 0,
            )
        )
    ).all()
    coverage_ratios = [
        min(1.0, (float(max_end_ms or 0) / 1000) / float(duration_seconds))
        for _, duration_seconds, max_end_ms in coverage_rows
    ]
    low_coverage_count = len(
        [
            ratio
            for ratio in coverage_ratios
            if ratio < settings.recording_monitoring_min_coverage_ratio
        ]
    )
    median_coverage = round(float(median(coverage_ratios)), 4) if coverage_ratios else None

    return {
        "status_counts": status_counts,
        "last_24h": {
            "total": last_24h_total,
            "ready": last_24h_counts.get("ready", 0),
            "failed": last_24h_counts.get("failed", 0),
            "processing": last_24h_counts.get("processing", 0),
        },
        "failed_rate_24h": round(failed_rate, 4),
        "stuck_processing_count": stuck_processing_count,
        "low_transcript_coverage_count_24h": low_coverage_count,
        "median_transcript_coverage_24h": median_coverage,
    }


def _observability_alerts(recording_pipeline: dict) -> list[dict]:
    settings = get_settings()
    alerts: list[dict] = []
    if recording_pipeline["stuck_processing_count"] > 0:
        alerts.append(
            {
                "severity": "critical",
                "code": "recording.processing.stuck",
                "title": "Stuck processing recordings",
                "value": recording_pipeline["stuck_processing_count"],
                "threshold": 0,
            }
        )
    if recording_pipeline["low_transcript_coverage_count_24h"] > 0:
        alerts.append(
            {
                "severity": "warning",
                "code": "recording.transcript.low_coverage",
                "title": "Low transcript coverage",
                "value": recording_pipeline["low_transcript_coverage_count_24h"],
                "threshold": settings.recording_monitoring_min_coverage_ratio,
            }
        )
    if (
        recording_pipeline["last_24h"]["total"]
        >= settings.recording_monitoring_min_volume_24h
        and recording_pipeline["failed_rate_24h"]
        >= settings.recording_monitoring_failure_rate_critical
    ):
        alerts.append(
            {
                "severity": "critical",
                "code": "recording.failed_rate.high",
                "title": "High recording failure rate",
                "value": recording_pipeline["failed_rate_24h"],
                "threshold": settings.recording_monitoring_failure_rate_critical,
            }
        )
    return alerts


async def _promo_response(
    promo: BillingPromoCode,
    db: Database,
    *,
    code: str | None = None,
    include_redemptions: bool = True,
) -> AdminPromoCodeResponse:
    plan = await db.get(Plan, promo.plan_id)
    redemption_payload: list[PromoRedemptionResponse] = []
    if include_redemptions:
        rows = (
            await db.execute(
                select(BillingPromoRedemption, User)
                .join(User, User.id == BillingPromoRedemption.user_id)
                .where(BillingPromoRedemption.promo_code_id == promo.id)
                .order_by(BillingPromoRedemption.created_at.desc())
            )
        ).all()
        redemption_payload = [
            PromoRedemptionResponse(
                user_id=str(redemption.user_id),
                user_email=user.email,
                subscription_id=str(redemption.subscription_id),
                redeemed_at=redemption.created_at,
            )
            for redemption, user in rows
        ]

    return AdminPromoCodeResponse(
        id=str(promo.id),
        code=code,
        normalized_code=normalize_promo_code(code) if code else None,
        plan=plan.code if plan is not None else "unknown",
        billing_period=promo.billing_period,
        duration_days=promo.duration_days,
        max_redemptions=promo.max_redemptions,
        redeemed_count=promo.redeemed_count,
        redemption_rate=promo.redeemed_count / promo.max_redemptions,
        active=promo.active,
        archived_at=promo.archived_at,
        expires_at=promo.expires_at,
        note=promo.note,
        created_at=promo.created_at,
        redemptions=redemption_payload,
    )


@router.post("/promo-codes", response_model=AdminPromoCodeResponse)
async def create_admin_promo_code(
    payload: AdminPromoCodeCreateRequest,
    db: Database,
    admin: CurrentAdmin,
) -> AdminPromoCodeResponse:
    """Create a hash-stored promo code and return the plaintext once."""
    plan = (await db.execute(select(Plan).where(Plan.code == payload.plan))).scalar_one_or_none()
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

    await _audit(
        db,
        admin,
        action="promo_create",
        target_type="promo_code",
        target_id=str(promo.id),
        details={"plan": plan.code, "max_redemptions": promo.max_redemptions},
    )
    return await _promo_response(promo, db, code=code, include_redemptions=False)


@router.get(
    "/promo-codes",
    response_model=AdminPromoCodeListResponse,
    response_model_exclude_none=True,
)
async def list_admin_promo_codes(
    db: Database,
    admin: CurrentAdmin,
    include_archived: bool = False,
    active: bool | None = None,
    limit: int = 100,
) -> AdminPromoCodeListResponse:
    del admin
    query = select(BillingPromoCode).order_by(desc(BillingPromoCode.created_at)).limit(
        min(max(limit, 1), 500)
    )
    if not include_archived:
        query = query.where(BillingPromoCode.archived_at.is_(None))
    if active is not None:
        query = query.where(BillingPromoCode.active.is_(active))
    promos = list((await db.execute(query)).scalars().all())
    return AdminPromoCodeListResponse(
        items=[await _promo_response(promo, db) for promo in promos]
    )


@router.get(
    "/promo-codes/{promo_id}",
    response_model=AdminPromoCodeResponse,
    response_model_exclude_none=True,
)
async def get_admin_promo_code(
    promo_id: UUID,
    db: Database,
    admin: CurrentAdmin,
) -> AdminPromoCodeResponse:
    del admin
    promo = await db.get(BillingPromoCode, promo_id)
    if promo is None:
        raise HTTPException(status_code=404, detail="Promo code not found")
    return await _promo_response(promo, db)


@router.patch(
    "/promo-codes/{promo_id}",
    response_model=AdminPromoCodeResponse,
    response_model_exclude_none=True,
)
async def patch_admin_promo_code(
    promo_id: UUID,
    payload: AdminPromoCodePatchRequest,
    db: Database,
    admin: CurrentAdmin,
) -> AdminPromoCodeResponse:
    promo = await db.get(BillingPromoCode, promo_id)
    if promo is None or promo.archived_at is not None:
        raise HTTPException(status_code=404, detail="Promo code not found")
    updates = payload.model_dump(exclude_unset=True)
    if "max_redemptions" in updates and updates["max_redemptions"] < promo.redeemed_count:
        raise HTTPException(
            status_code=400,
            detail="max_redemptions cannot be lower than redeemed_count",
        )
    for field_name, value in updates.items():
        setattr(promo, field_name, value)
    await db.flush()
    await _audit(
        db,
        admin,
        action="promo_update",
        target_type="promo_code",
        target_id=str(promo.id),
        details={"fields": sorted(updates.keys())},
    )
    return await _promo_response(promo, db)


@router.delete("/promo-codes/{promo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_admin_promo_code(
    promo_id: UUID,
    db: Database,
    admin: CurrentAdmin,
) -> Response:
    promo = await db.get(BillingPromoCode, promo_id)
    if promo is None or promo.archived_at is not None:
        raise HTTPException(status_code=404, detail="Promo code not found")
    promo.archived_at = datetime.now(timezone.utc)
    promo.active = False
    await db.flush()
    await _audit(
        db,
        admin,
        action="promo_archive",
        target_type="promo_code",
        target_id=str(promo.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _user_summary(user: User, db: Database) -> AdminUserSummary:
    sub: Subscription | None = None
    plan_name = "free"
    if user.current_subscription_id is not None:
        sub = await db.get(Subscription, user.current_subscription_id)
        if sub is not None:
            plan = await db.get(Plan, sub.plan_id)
            plan_name = plan.code if plan is not None else "unknown"
    dictation_words = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(DictationEntry.word_count), 0)).where(
                    DictationEntry.user_id == user.id
                )
            )
        ).scalar_one()
    )
    recording_stats = (
        await db.execute(
            select(
                func.coalesce(func.sum(Recording.billed_word_count), 0),
                func.count(Recording.id),
            ).where(Recording.user_id == user.id)
        )
    ).one()
    return AdminUserSummary(
        id=str(user.id),
        email=user.email,
        account_status=user.account_status,
        account_status_reason=user.account_status_reason,
        created_at=user.created_at,
        current_plan=plan_name,
        current_subscription_status=sub.status if sub is not None else None,
        current_subscription_provider=sub.provider if sub is not None else None,
        dictation_words=dictation_words,
        recording_words=int(recording_stats[0] or 0),
        recording_count=int(recording_stats[1] or 0),
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_admin_users(
    db: Database,
    admin: CurrentAdmin,
    q: str | None = None,
    account_status: Literal["active", "paused", "deactivated"] | None = None,
    include_staff: bool = False,
    limit: int = 100,
) -> AdminUserListResponse:
    del admin
    query = select(User).order_by(desc(User.created_at)).limit(min(max(limit, 1), 500))
    if not include_staff:
        query = query.where(_customer_user_filter())
    if account_status is not None:
        query = query.where(User.account_status == account_status)
    if q:
        query = query.where(or_(User.email.ilike(f"%{q}%"), User.id.cast(String).ilike(f"%{q}%")))
    users = list((await db.execute(query)).scalars().all())
    return AdminUserListResponse(items=[await _user_summary(user, db) for user in users])


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_admin_user(
    user_id: UUID,
    db: Database,
    admin: CurrentAdmin,
) -> AdminUserDetail:
    del admin
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    summary = await _user_summary(user, db)
    subscriptions = (
        await db.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.user_id == user.id)
            .order_by(desc(Subscription.created_at))
        )
    ).all()
    redemptions = (
        await db.execute(
            select(BillingPromoRedemption, BillingPromoCode)
            .join(BillingPromoCode, BillingPromoCode.id == BillingPromoRedemption.promo_code_id)
            .where(BillingPromoRedemption.user_id == user.id)
            .order_by(desc(BillingPromoRedemption.created_at))
        )
    ).all()
    usage_rows = (
        await db.execute(
            select(UsageWeek)
            .where(UsageWeek.user_id == user.id)
            .order_by(desc(UsageWeek.week_start_utc))
            .limit(12)
        )
    ).scalars().all()
    return AdminUserDetail(
        **summary.model_dump(),
        subscriptions=[
            {
                "id": str(sub.id),
                "plan": plan.code,
                "status": sub.status,
                "provider": sub.provider,
                "billing_period": sub.billing_period,
                "current_period_end": sub.current_period_end.isoformat()
                if sub.current_period_end
                else None,
                "cancel_at_period_end": sub.cancel_at_period_end,
            }
            for sub, plan in subscriptions
        ],
        promo_redemptions=[
            {
                "promo_code_id": str(redemption.promo_code_id),
                "subscription_id": str(redemption.subscription_id),
                "redeemed_at": redemption.created_at.isoformat(),
                "promo_note": promo.note,
            }
            for redemption, promo in redemptions
        ],
        weekly_usage=[
            {
                "week_start_utc": row.week_start_utc.isoformat(),
                "words_used": row.words_used,
            }
            for row in usage_rows
        ],
    )


@router.patch("/users/{user_id}/status", response_model=AdminUserSummary)
async def patch_admin_user_status(
    user_id: UUID,
    payload: AdminUserStatusPatchRequest,
    db: Database,
    admin: CurrentAdmin,
) -> AdminUserSummary:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.user.id and payload.status != "active":
        raise HTTPException(status_code=400, detail="Admins cannot pause their own account")
    now = datetime.now(timezone.utc)
    user.account_status = payload.status
    user.account_status_reason = payload.reason
    user.account_status_changed_at = now
    user.account_status_changed_by_user_id = admin.user.id
    if payload.status == "deactivated":
        await db.execute(delete_tokens_stmt(RefreshToken, user.id))
        await db.execute(
            update(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.execute(
            update(McpOAuthToken)
            .where(McpOAuthToken.user_id == user.id, McpOAuthToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    await db.flush()
    await _audit(
        db,
        admin,
        action="user_status_update",
        target_type="user",
        target_id=str(user.id),
        reason=payload.reason,
        details={"status": payload.status},
    )
    return await _user_summary(user, db)


def delete_tokens_stmt(model, user_id: UUID):
    return (
        update(model)
        .where(model.user_id == user_id)
        .values(expires_at=datetime.now(timezone.utc))
    )


def _subscription_response(sub: Subscription, plan: Plan) -> AdminSubscriptionResponse:
    return AdminSubscriptionResponse(
        id=str(sub.id),
        user_id=str(sub.user_id),
        plan=plan.code,
        status=sub.status,
        provider=sub.provider,
        billing_period=sub.billing_period,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
    )


@router.post("/users/{user_id}/subscriptions/grant", response_model=AdminSubscriptionResponse)
async def grant_admin_subscription(
    user_id: UUID,
    payload: AdminGrantSubscriptionRequest,
    db: Database,
    admin: CurrentAdmin,
) -> AdminSubscriptionResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    plan = (await db.execute(select(Plan).where(Plan.code == "pro"))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=500, detail="Pro plan missing")
    now = datetime.now(timezone.utc)
    sub: Subscription | None = None
    if user.current_subscription_id is not None:
        current = await db.get(Subscription, user.current_subscription_id)
        if current is not None and current.provider == BillingProvider.ADMIN.value:
            sub = current
    if sub is None:
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            provider=BillingProvider.ADMIN.value,
            billing_period=BillingPeriod.MONTH.value,
            current_period_start=now,
            current_period_end=now + timedelta(days=payload.duration_days),
            cancel_at_period_end=True,
        )
        db.add(sub)
        await db.flush()
        user.current_subscription_id = sub.id
    else:
        base = (
            sub.current_period_end
            if sub.current_period_end and sub.current_period_end > now
            else now
        )
        sub.current_period_end = base + timedelta(days=payload.duration_days)
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.cancel_at_period_end = True
    await db.flush()
    await _audit(
        db,
        admin,
        action="subscription_grant",
        target_type="subscription",
        target_id=str(sub.id),
        reason=payload.reason,
        details={"user_id": str(user.id), "duration_days": payload.duration_days},
        subscription_id=sub.id,
    )
    return _subscription_response(sub, plan)


@router.post("/subscriptions/{subscription_id}/cancel", response_model=AdminSubscriptionResponse)
async def cancel_admin_subscription(
    subscription_id: UUID,
    payload: AdminSubscriptionActionRequest,
    db: Database,
    admin: CurrentAdmin,
) -> AdminSubscriptionResponse:
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    plan = await db.get(Plan, sub.plan_id)
    if plan is None:
        raise HTTPException(status_code=500, detail="Subscription plan missing")
    now = datetime.now(timezone.utc)
    if sub.provider == BillingProvider.STRIPE.value:
        if not sub.stripe_subscription_id:
            raise HTTPException(status_code=400, detail="Stripe subscription id missing")
        await StripeProvider().cancel_subscription(
            sub.stripe_subscription_id,
            at_period_end=payload.mode == "period_end",
        )
    if payload.mode == "immediate":
        sub.status = SubscriptionStatus.CANCELED.value
        sub.canceled_at = now
        sub.cancel_at_period_end = False
    else:
        sub.cancel_at_period_end = True
    await db.flush()
    await _audit(
        db,
        admin,
        action="subscription_cancel",
        target_type="subscription",
        target_id=str(sub.id),
        reason=payload.reason,
        details={"mode": payload.mode, "provider": sub.provider},
        subscription_id=sub.id,
    )
    return _subscription_response(sub, plan)


@router.get("/billing", response_model=AdminBillingListResponse)
async def list_admin_billing(
    db: Database,
    admin: CurrentAdmin,
    limit: int = 100,
) -> AdminBillingListResponse:
    del admin
    rows = (
        await db.execute(
            select(Subscription, Plan, User)
            .join(Plan, Plan.id == Subscription.plan_id)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.user_id.not_in(_staff_user_ids_query()))
            .order_by(desc(Subscription.created_at))
            .limit(min(max(limit, 1), 500))
        )
    ).all()
    items: list[AdminBillingSubscriptionListItem] = []
    for sub, plan, user in rows:
        invoices = (
            await db.execute(
                select(Invoice)
                .where(Invoice.subscription_id == sub.id)
                .order_by(desc(Invoice.created_at))
            )
        ).scalars().all()
        items.append(
            AdminBillingSubscriptionListItem(
                id=str(sub.id),
                user_id=str(sub.user_id),
                user_email=user.email,
                plan=plan.code,
                status=sub.status,
                provider=sub.provider,
                billing_period=sub.billing_period,
                current_period_end=sub.current_period_end,
                cancel_at_period_end=sub.cancel_at_period_end,
                invoices=[
                    AdminBillingInvoiceResponse(
                        id=str(invoice.id),
                        amount=float(invoice.amount),
                        currency=invoice.currency,
                        status=invoice.status,
                        provider_payment_id=invoice.provider_payment_id,
                        paid_at=invoice.paid_at,
                        created_at=invoice.created_at,
                    )
                    for invoice in invoices
                ],
            )
        )
    return AdminBillingListResponse(items=items)


@router.post("/subscriptions/{subscription_id}/resume", response_model=AdminSubscriptionResponse)
async def resume_admin_subscription(
    subscription_id: UUID,
    payload: AdminReasonRequest,
    db: Database,
    admin: CurrentAdmin,
) -> AdminSubscriptionResponse:
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    plan = await db.get(Plan, sub.plan_id)
    if plan is None:
        raise HTTPException(status_code=500, detail="Subscription plan missing")
    if sub.provider == BillingProvider.STRIPE.value:
        if not sub.stripe_subscription_id:
            raise HTTPException(status_code=400, detail="Stripe subscription id missing")
        await StripeProvider().resume_subscription(sub.stripe_subscription_id)
    if sub.status == SubscriptionStatus.CANCELED.value:
        sub.status = SubscriptionStatus.ACTIVE.value
    sub.cancel_at_period_end = False
    sub.canceled_at = None
    await db.flush()
    await _audit(
        db,
        admin,
        action="subscription_resume",
        target_type="subscription",
        target_id=str(sub.id),
        reason=payload.reason,
        details={"provider": sub.provider},
        subscription_id=sub.id,
    )
    return _subscription_response(sub, plan)


@router.post("/invoices/{invoice_id}/refund")
async def refund_admin_invoice(
    invoice_id: UUID,
    payload: AdminRefundRequest,
    db: Database,
    admin: CurrentAdmin,
) -> dict:
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    sub = await db.get(Subscription, invoice.subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if not invoice.provider_payment_id:
        raise HTTPException(status_code=400, detail="Invoice has no provider payment id")
    provider_result: dict | None = None
    if sub.provider == BillingProvider.STRIPE.value:
        provider_result = await StripeProvider().refund_payment(
            invoice.provider_payment_id,
            amount_minor=payload.amount_minor,
            reason=payload.reason,
        )
    elif sub.provider == BillingProvider.TINKOFF.value:
        provider_result = await TinkoffProvider().cancel_payment(
            invoice.provider_payment_id,
            amount_kopecks=payload.amount_minor,
        )
    else:
        raise HTTPException(status_code=400, detail="Provider does not support refunds")
    full_amount_minor = int(Decimal(invoice.amount) * 100)
    invoice.status = (
        "refunded"
        if payload.amount_minor is None or payload.amount_minor >= full_amount_minor
        else "partially_refunded"
    )
    await db.flush()
    await _audit(
        db,
        admin,
        action="invoice_refund",
        target_type="invoice",
        target_id=str(invoice.id),
        reason=payload.reason,
        details={
            "provider": sub.provider,
            "provider_payment_id": invoice.provider_payment_id,
            "amount_minor": payload.amount_minor,
            "provider_result": provider_result,
        },
        subscription_id=sub.id,
    )
    return {"status": invoice.status, "provider_result": provider_result}


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(db: Database, admin: CurrentAdmin) -> AdminStatsResponse:
    del admin
    now = datetime.now(timezone.utc)
    monthly_since = now - timedelta(days=366)
    user_counts = dict(
        (status_value, int(count))
        for status_value, count in (
            await db.execute(
                select(User.account_status, func.count(User.id))
                .where(_customer_user_filter())
                .group_by(User.account_status)
            )
        ).all()
    )
    total_users = int(
        (
            await db.execute(select(func.count(User.id)).where(_customer_user_filter()))
        ).scalar_one()
    )
    new_users_30d = int(
        (
            await db.execute(
                select(func.count(User.id)).where(
                    _customer_user_filter(),
                    User.created_at >= now - timedelta(days=30),
                )
            )
        ).scalar_one()
    )

    promo_rows = (await db.execute(select(BillingPromoCode))).scalars().all()
    expired = 0
    active = 0
    archived = 0
    exhausted = 0
    for promo in promo_rows:
        if promo.archived_at is not None:
            archived += 1
        if promo.expires_at is not None and promo.expires_at <= now:
            expired += 1
        if promo.redeemed_count >= promo.max_redemptions:
            exhausted += 1
        if promo.active and promo.archived_at is None:
            active += 1
    redemptions = int(
        (
            await db.execute(
                select(func.count(BillingPromoRedemption.id)).where(
                    BillingPromoRedemption.user_id.not_in(_staff_user_ids_query())
                )
            )
        ).scalar_one()
    )

    recording_words = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(Recording.billed_word_count), 0)).where(
                    Recording.user_id.not_in(_staff_user_ids_query())
                )
            )
        ).scalar_one()
    )
    recording_duration = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(Recording.duration_seconds), 0)).where(
                    Recording.user_id.not_in(_staff_user_ids_query())
                )
            )
        ).scalar_one()
    )
    recording_count = int(
        (
            await db.execute(
                select(func.count(Recording.id)).where(
                    Recording.user_id.not_in(_staff_user_ids_query())
                )
            )
        ).scalar_one()
    )
    failed_recordings = int(
        (
            await db.execute(
                select(func.count(Recording.id)).where(
                    Recording.user_id.not_in(_staff_user_ids_query()),
                    Recording.status == "failed",
                )
            )
        ).scalar_one()
    )
    dictation_words = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(DictationEntry.word_count), 0)).where(
                    DictationEntry.user_id.not_in(_staff_user_ids_query())
                )
            )
        ).scalar_one()
    )
    dictation_duration = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(DictationEntry.duration_seconds), 0)).where(
                    DictationEntry.user_id.not_in(_staff_user_ids_query())
                )
            )
        ).scalar_one()
    )

    subscription_by_provider = dict(
        (provider, int(count))
        for provider, count in (
            await db.execute(
                select(Subscription.provider, func.count(Subscription.id))
                .where(Subscription.user_id.not_in(_staff_user_ids_query()))
                .group_by(Subscription.provider)
            )
        ).all()
    )
    subscription_by_status = dict(
        (status_value, int(count))
        for status_value, count in (
            await db.execute(
                select(Subscription.status, func.count(Subscription.id))
                .where(Subscription.user_id.not_in(_staff_user_ids_query()))
                .group_by(Subscription.status)
            )
        ).all()
    )
    revenue_by_currency = dict(
        (currency, float(amount or 0))
        for currency, amount in (
            await db.execute(
                select(Invoice.currency, func.coalesce(func.sum(Invoice.amount), 0))
                .join(Subscription, Subscription.id == Invoice.subscription_id)
                .where(
                    Subscription.user_id.not_in(_staff_user_ids_query()),
                    Invoice.status == "paid",
                )
                .group_by(Invoice.currency)
            )
        ).all()
    )
    monthly_usage = await _usage_buckets(db, grain="month", since=monthly_since)
    yearly_usage = await _usage_buckets(db, grain="year", since=None)
    monthly_revenue = await _monthly_revenue(db, since=monthly_since)
    monthly_redemptions = await _monthly_promo_redemptions(db, since=monthly_since)
    return AdminStatsResponse(
        users={
            "total": total_users,
            "new_30d": new_users_30d,
            "by_status": user_counts,
        },
        promo={
            "total": len(promo_rows),
            "active": active,
            "paused": len(
                [
                    promo
                    for promo in promo_rows
                    if not promo.active and promo.archived_at is None
                ]
            ),
            "archived": archived,
            "expired": expired,
            "exhausted": exhausted,
            "redemptions": redemptions,
            "monthly_redemptions": monthly_redemptions,
        },
        usage={
            "recording_words": recording_words,
            "dictation_words": dictation_words,
            "total_words": recording_words + dictation_words,
            "recording_duration_seconds": recording_duration,
            "dictation_duration_seconds": dictation_duration,
            "recording_count": recording_count,
            "failed_recordings": failed_recordings,
            "monthly": monthly_usage,
            "yearly": yearly_usage,
        },
        billing={
            "subscriptions_by_provider": subscription_by_provider,
            "subscriptions_by_status": subscription_by_status,
            "revenue_by_currency": revenue_by_currency,
            "monthly_revenue": monthly_revenue,
        },
    )


@router.get("/observability", response_model=AdminObservabilityResponse)
async def get_admin_observability(db: Database, admin: CurrentAdmin) -> AdminObservabilityResponse:
    del admin
    settings = get_settings()
    now = datetime.now(timezone.utc)
    await db.execute(text("SELECT 1"))
    recording_pipeline = await _recording_pipeline_observability(db, now=now)
    sentry_runtime = get_sentry_runtime()
    sentry_runtime.update(
        {
            "configured": bool(settings.sentry_dsn),
            "release": sentry_runtime.get("release") or get_release_version(),
            "environment": sentry_runtime.get("environment")
            or ("production" if not settings.debug else "development"),
            "traces_sample_rate": settings.sentry_traces_sample_rate,
            "profiles_sample_rate": settings.sentry_profiles_sample_rate,
        }
    )
    return AdminObservabilityResponse(
        generated_at=now,
        server={
            "database": "connected",
            "release": get_release_version(),
            "environment": "production" if not settings.debug else "development",
            "log_format": settings.log_format,
        },
        sentry=sentry_runtime,
        recording_pipeline=recording_pipeline,
        alerts=_observability_alerts(recording_pipeline),
    )


@router.get("/audit")
async def list_admin_audit(db: Database, admin: CurrentAdmin, limit: int = 100) -> dict:
    del admin
    rows = (
        await db.execute(
            select(AdminAuditLog)
            .order_by(desc(AdminAuditLog.created_at))
            .limit(min(max(limit, 1), 500))
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(row.id),
                "actor_staff_member_id": str(row.actor_staff_member_id)
                if row.actor_staff_member_id
                else None,
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "reason": row.reason,
                "details": row.details,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }
