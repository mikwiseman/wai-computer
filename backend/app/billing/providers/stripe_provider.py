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
        discount_percent: int | None = None,
        discount_code: str | None = None,
        promo_code_id: str | None = None,
    ) -> CheckoutResult:
        client = self._client_or_raise()
        settings = get_settings()
        price_id = await self._resolve_price_id(plan_code=plan_code, period=period)
        metadata = {"user_id": user_id, "plan_code": plan_code, "period": period}
        if promo_code_id:
            metadata["promo_code_id"] = promo_code_id
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "customer_email": user_email,
            "client_reference_id": user_id,
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
        }
        if discount_percent is not None:
            coupon = await client.v1.coupons.create_async(
                params={
                    "percent_off": discount_percent,
                    "duration": "once",
                    "name": discount_code or f"{discount_percent}% off",
                }
            )
            params["discounts"] = [{"coupon": coupon.id}]
        if settings.stripe_automatic_tax:
            params["automatic_tax"] = {"enabled": True}
        session = await client.v1.checkout.sessions.create_async(params=params)
        return CheckoutResult(
            checkout_url=session.url,  # type: ignore[arg-type]
            provider=self.name,
            provider_session_id=session.id,
        )

    async def cancel_subscription(
        self,
        provider_subscription_id: str,
        *,
        at_period_end: bool = True,
    ) -> None:
        client = self._client_or_raise()
        if at_period_end:
            await client.v1.subscriptions.update_async(
                provider_subscription_id,
                params={"cancel_at_period_end": True},
            )
            return
        await client.v1.subscriptions.cancel_async(provider_subscription_id)

    async def resume_subscription(self, provider_subscription_id: str) -> None:
        client = self._client_or_raise()
        await client.v1.subscriptions.update_async(
            provider_subscription_id,
            params={"cancel_at_period_end": False},
        )

    async def refund_payment(
        self,
        payment_id: str,
        *,
        amount_minor: int | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        client = self._client_or_raise()
        params: dict[str, Any] = {"payment_intent": payment_id}
        if amount_minor is not None:
            params["amount"] = amount_minor
        if reason:
            params["reason"] = reason
        refund = await client.v1.refunds.create_async(params=params)
        if hasattr(refund, "to_dict"):
            return refund.to_dict()
        if hasattr(refund, "to_dict_recursive"):
            return refund.to_dict_recursive()
        return dict(refund)

    async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> ProviderEvent:
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

        if hasattr(event, "to_dict"):
            raw_event = event.to_dict()
        elif hasattr(event, "to_dict_recursive"):
            raw_event = event.to_dict_recursive()
        else:
            raw_event = dict(event)

        obj: dict[str, Any] = raw_event.get("data", {}).get("object", {})
        event_type: str = raw_event["type"]
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
            raw=raw_event,
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
            raise ProviderUnavailableError(f"Plan '{plan_code}' not found")
        price_id = plan.stripe_price_id_yearly if period == "year" else plan.stripe_price_id_monthly
        if not price_id:
            raise ProviderUnavailableError(
                f"Plan '{plan_code}' has no Stripe price id for period '{period}'"
            )
        return price_id
