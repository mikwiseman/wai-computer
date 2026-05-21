"""Endpoint-level billing checkout/webhook/subscription integration tests."""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import ProviderUnavailableError
from app.billing.providers.stripe_provider import StripeProvider
from app.billing.providers.tinkoff_provider import (
    TinkoffProvider,
    generate_tinkoff_token,
    verify_tinkoff_token,
)
from app.models.billing import Subscription
from app.models.user import User


class BillingTestSettings:
    frontend_url = "https://wai.computer"
    stripe_secret_key = "sk_test_endpoint"
    stripe_webhook_secret = "whsec_endpoint"
    stripe_automatic_tax = False
    tinkoff_api_url = "https://securepay.tinkoff.ru/v2/"
    tinkoff_terminal_key = "terminal"
    tinkoff_password = "pw"
    billing_enforcement_enabled = False


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    payload = response.json()
    return payload["access_token"], f"Bearer {payload['access_token']}"


async def _user_id(db_session: AsyncSession, email: str) -> str:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    return str(user.id)


def _stripe_signature(payload: dict[str, Any], secret: str) -> tuple[bytes, str]:
    payload_text = json.dumps(payload, separators=(",", ":"))
    timestamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(
        f"{timestamp}.{payload_text}",
        secret,
    )
    return payload_text.encode("utf-8"), f"t={timestamp},v1={signature}"


def _patch_billing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = BillingTestSettings()
    monkeypatch.setattr("app.billing.router.get_settings", lambda: settings)
    monkeypatch.setattr("app.billing.providers.stripe_provider.get_settings", lambda: settings)
    monkeypatch.setattr("app.billing.providers.tinkoff_provider.get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_stripe_checkout_webhook_updates_subscription_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_billing_settings(monkeypatch)
    email = "stripe.checkout.e2e@example.com"
    _, bearer = await _register(client, email)
    user_id = await _user_id(db_session, email)
    captured: dict[str, Any] = {}

    class FakeSession:
        id = "cs_test_endpoint"
        url = "https://checkout.stripe.test/session"

    class FakeSessions:
        async def create_async(self, *, params: dict[str, Any]) -> FakeSession:
            captured.update(params)
            return FakeSession()

    class FakeCheckout:
        sessions = FakeSessions()

    class FakeV1:
        checkout = FakeCheckout()

    class FakeClient:
        v1 = FakeV1()

    async def fake_resolve_price_id(
        self: StripeProvider,
        *,
        plan_code: str,
        period: str,
    ) -> str:
        assert plan_code == "pro"
        assert period == "month"
        return "price_test_pro_month"

    original_client_or_raise = StripeProvider._client_or_raise
    monkeypatch.setattr(StripeProvider, "_resolve_price_id", fake_resolve_price_id)
    monkeypatch.setattr(StripeProvider, "_client_or_raise", lambda self: FakeClient())

    checkout = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": bearer},
        json={"plan": "pro", "period": "month", "provider": "stripe"},
    )

    assert checkout.status_code == 200
    assert checkout.json() == {
        "provider": "stripe",
        "checkout_url": "https://checkout.stripe.test/session",
    }
    assert captured["mode"] == "subscription"
    assert captured["line_items"] == [{"price": "price_test_pro_month", "quantity": 1}]
    assert captured["success_url"] == "https://wai.computer/billing/success"
    assert captured["cancel_url"] == "https://wai.computer/billing/cancel"
    assert captured["client_reference_id"] == user_id
    assert captured["metadata"] == {
        "user_id": user_id,
        "plan_code": "pro",
        "period": "month",
    }

    monkeypatch.setattr(StripeProvider, "_client_or_raise", original_client_or_raise)
    event_payload = {
        "id": "evt_checkout_endpoint",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_endpoint",
                "object": "checkout.session",
                "client_reference_id": user_id,
                "subscription": "sub_endpoint",
                "customer": "cus_endpoint",
                "metadata": {"plan_code": "pro", "period": "month"},
            }
        },
    }
    body, signature = _stripe_signature(
        event_payload,
        BillingTestSettings.stripe_webhook_secret,
    )
    webhook = await client.post(
        "/api/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )

    assert webhook.status_code == 200
    assert webhook.json() == {"received": True, "type": "checkout.session.completed"}

    subscription = await client.get(
        "/api/billing/subscription",
        headers={"Authorization": bearer},
    )
    assert subscription.status_code == 200
    payload = subscription.json()
    assert payload["plan"]["code"] == "pro"
    assert payload["status"] == "active"
    assert payload["provider"] == "stripe"
    assert payload["billing_period"] == "month"

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == "sub_endpoint")
        )
    ).scalar_one()
    assert sub.stripe_customer_id == "cus_endpoint"


@pytest.mark.asyncio
async def test_tinkoff_checkout_webhook_updates_subscription_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_billing_settings(monkeypatch)

    @asynccontextmanager
    async def fake_db_context():
        yield db_session

    monkeypatch.setattr("app.db.session.get_db_context", fake_db_context)

    captured: dict[str, Any] = {}

    async def fake_call(
        self: TinkoffProvider,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        captured["method"] = method
        captured["payload"] = payload
        return {
            "Success": True,
            "PaymentURL": "https://securepay.tinkoff.ru/new/endpoint",
            "PaymentId": "payment-endpoint",
        }

    monkeypatch.setattr(TinkoffProvider, "_call", fake_call)

    email = "tinkoff.checkout.e2e@example.com"
    _, bearer = await _register(client, email)
    user_id = await _user_id(db_session, email)

    checkout = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": bearer},
        json={"plan": "pro", "period": "year", "provider": "tinkoff"},
    )

    assert checkout.status_code == 200
    assert checkout.json() == {
        "provider": "tinkoff",
        "checkout_url": "https://securepay.tinkoff.ru/new/endpoint",
    }
    assert captured["method"] == "Init"
    init_payload = captured["payload"]
    assert init_payload["Amount"] == 799900
    assert init_payload["PayType"] == "O"
    assert init_payload["Recurrent"] == "Y"
    assert init_payload["CustomerKey"] == user_id
    assert init_payload["SuccessURL"] == (
        "https://wai.computer/billing/success?provider=tinkoff&lang=ru"
    )
    assert init_payload["FailURL"] == (
        "https://wai.computer/billing/cancel?provider=tinkoff&lang=ru"
    )
    assert init_payload["NotificationURL"] == "https://wai.computer/api/webhooks/tinkoff"
    assert init_payload["DATA"] == {
        "user_id": user_id,
        "plan_code": "pro",
        "period": "year",
    }
    assert verify_tinkoff_token(init_payload, BillingTestSettings.tinkoff_password)

    notification = {
        "TerminalKey": BillingTestSettings.tinkoff_terminal_key,
        "OrderId": init_payload["OrderId"],
        "Status": "CONFIRMED",
        "Success": True,
        "PaymentId": "payment-endpoint",
        "Amount": 799900,
        "CustomerKey": user_id,
        "RebillId": "rebill-endpoint",
        "DATA": {"user_id": user_id, "plan_code": "pro", "period": "year"},
    }
    token = generate_tinkoff_token(notification, BillingTestSettings.tinkoff_password)
    webhook = await client.post(
        "/api/webhooks/tinkoff",
        content=json.dumps({**notification, "Token": token}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    assert webhook.status_code == 200
    assert webhook.text == "OK"

    subscription = await client.get(
        "/api/billing/subscription",
        headers={"Authorization": bearer},
    )
    assert subscription.status_code == 200
    payload = subscription.json()
    assert payload["plan"]["code"] == "pro"
    assert payload["status"] == "active"
    assert payload["provider"] == "tinkoff"
    assert payload["billing_period"] == "year"


@pytest.mark.asyncio
async def test_stripe_webhook_maps_provider_and_validation_errors(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableStripeProvider:
        async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]):
            raise ProviderUnavailableError("stripe not configured")

    class InvalidStripeProvider:
        async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]):
            raise ValueError("bad stripe signature")

    monkeypatch.setattr("app.billing.webhooks.StripeProvider", UnavailableStripeProvider)
    unavailable = await client.post("/api/webhooks/stripe", content=b"{}")

    monkeypatch.setattr("app.billing.webhooks.StripeProvider", InvalidStripeProvider)
    invalid = await client.post("/api/webhooks/stripe", content=b"{}")

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "stripe not configured"
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "bad stripe signature"


@pytest.mark.asyncio
async def test_tinkoff_webhook_maps_provider_and_validation_errors(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableTinkoffProvider:
        async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]):
            raise ProviderUnavailableError("tinkoff not configured")

    class InvalidTinkoffProvider:
        async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]):
            raise ValueError("bad tinkoff token")

    monkeypatch.setattr("app.billing.webhooks.TinkoffProvider", UnavailableTinkoffProvider)
    unavailable = await client.post("/api/webhooks/tinkoff", content=b"{}")

    monkeypatch.setattr("app.billing.webhooks.TinkoffProvider", InvalidTinkoffProvider)
    invalid = await client.post("/api/webhooks/tinkoff", content=b"{}")

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "tinkoff not configured"
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "bad tinkoff token"
