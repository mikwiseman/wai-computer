"""Shared subscription entitlement helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.billing import BillingProvider, Subscription


def subscription_is_entitled(sub: Subscription, *, now: datetime | None = None) -> bool:
    if sub.status not in {"active", "trialing"}:
        return False
    if sub.provider == BillingProvider.PROMO.value and sub.current_period_end is not None:
        current_time = now or datetime.now(timezone.utc)
        period_end = sub.current_period_end
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=timezone.utc)
        return period_end > current_time
    return True
