"""Stripe provider — Subscriptions API + Checkout + webhook verification.

Port of wai-pay/backend/src/providers/stripe/index.ts for the WaiComputer
subscription model. Subscriptions only — no one-time payment paths.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.billing.providers.base import (
    CheckoutResult,
    PaymentProvider,
    ProviderEvent,
    ProviderUnavailableError,
)
from app.config import get_settings

logger = logging.getLogger(__name__)


# Map raw Stripe subscription statuses to our normalized strings. Stripe and
# our `SubscriptionStatus` already align except that "unpaid" doesn't exist
# on our side — fold it into "past_due" so we don't lose entitlement signal.
_STATUS_MAP = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete": "incomplete",
    "incomplete_expired": "expired",
    "paused": "past_due",
}


def _normalize_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    return _STATUS_MAP.get(raw, raw)


class StripeProvider(PaymentProvider):
    """Hosted-checkout Stripe Subscriptions provider."""

    name = "stripe"

    def __init__(self, secret_key: str | None = None, webhook_secret: str | None = None) -> None:
        settings = get_settings()
        self._secret_key = secret_key or settings.stripe_secret_key
        self._webhook_secret = webhook_secret or settings.stripe_webhook_secret
        self._client: stripe.StripeClient | None = None

    def _client_or_raise(self) -> stripe.StripeClient:
        if not self._secret_key:
            raise ProviderUnavailableError("STRIPE_SECRET_KEY not configured")
        if self._client is None:
            self._client = stripe.StripeClient(self._secret_key)
        return self._client

    async def create_checkout(
        self,
        *,
        plan_code: str,
        period: str,
        user_email: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int | None = None,
    ) -> CheckoutResult:
        client = self._client_or_raise()
        price_id = await self._resolve_price_id(plan_code=plan_code, period=period)
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "customer_email": user_email,
            "client_reference_id": user_id,
            "automatic_tax": {"enabled": True},
            "metadata": {"user_id": user_id, "plan_code": plan_code, "period": period},
            "subscription_data": {
                "metadata": {"user_id": user_id, "plan_code": plan_code, "period": period},
            },
        }
        if trial_days and trial_days > 0:
            params["subscription_data"]["trial_period_days"] = trial_days

        session = await client.checkout.sessions.create_async(params=params)
        return CheckoutResult(
            checkout_url=session.url,  # type: ignore[arg-type]
            provider=self.name,
            provider_session_id=session.id,
        )

    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        client = self._client_or_raise()
        await client.subscriptions.update_async(
            provider_subscription_id,
            params={"cancel_at_period_end": True},
        )

    async def parse_webhook(
        self, *, raw_body: bytes, headers: dict[str, str]
    ) -> ProviderEvent:
        if not self._webhook_secret:
            raise ProviderUnavailableError("STRIPE_WEBHOOK_SECRET not configured")
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not sig:
            raise ValueError("Missing Stripe-Signature header")
        client = self._client_or_raise()
        try:
            event = client.construct_event(raw_body.decode("utf-8"), sig, self._webhook_secret)
        except stripe.SignatureVerificationError as exc:  # type: ignore[attr-defined]
            raise ValueError(f"Invalid Stripe webhook signature: {exc}") from exc

        obj: dict[str, Any] = event["data"]["object"] if "data" in event else {}
        event_type: str = event["type"]
        subscription_id = None
        customer_id = obj.get("customer") if isinstance(obj, dict) else None
        status = None

        if event_type.startswith("customer.subscription."):
            subscription_id = obj.get("id")
            status = _normalize_status(obj.get("status"))
        elif event_type.startswith("invoice."):
            subscription_id = obj.get("subscription")

        return ProviderEvent(
            type=event_type,
            subscription_id_provider=subscription_id,
            customer_id_provider=customer_id,
            status=status,
            raw=event,
        )

    # ------------------------------------------------------------------
    async def _resolve_price_id(self, *, plan_code: str, period: str) -> str:
        """Resolve the Stripe Price ID for (plan_code, period) from billing_plans."""
        from sqlalchemy import select

        from app.db.session import get_db_context
        from app.models.billing import Plan

        async with get_db_context() as db:
            plan = (
                await db.execute(select(Plan).where(Plan.code == plan_code))
            ).scalar_one_or_none()
        if plan is None:
            raise ValueError(f"Plan '{plan_code}' not found")
        price_id = (
            plan.stripe_price_id_yearly if period == "year" else plan.stripe_price_id_monthly
        )
        if not price_id:
            raise ValueError(
                f"Plan '{plan_code}' has no Stripe price id for period '{period}'"
            )
        return price_id
