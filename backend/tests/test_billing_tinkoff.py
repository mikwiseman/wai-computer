"""Tests for the T-Bank rail: signature, webhook parsing, receipt shape."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import ProviderEvent, ProviderUnavailableError
from app.billing.providers.tinkoff_provider import (
    TinkoffProvider,
    build_receipt,
    generate_tinkoff_token,
    verify_tinkoff_token,
)
from app.billing.router import _checkout_result_urls
from app.billing.service import apply_tinkoff_event
from app.billing.webhooks import _tinkoff_ack_response
from app.models.billing import Invoice, Plan, Subscription
from app.models.user import User


def test_token_is_deterministic_and_sorted():
    params = {"TerminalKey": "test", "Amount": 12000, "OrderId": "abc"}
    t1 = generate_tinkoff_token(params, "pw")
    t2 = generate_tinkoff_token(dict(reversed(list(params.items()))), "pw")
    assert t1 == t2
    assert len(t1) == 64  # SHA-256 hex


def test_token_excludes_nested_structures():
    """Receipt, DATA, Token itself must NOT contribute to the signature."""
    base = {"TerminalKey": "k", "Amount": 100}
    sig_a = generate_tinkoff_token(base, "pw")
    sig_b = generate_tinkoff_token({**base, "DATA": {"x": 1}, "Receipt": {"Items": []}}, "pw")
    assert sig_a == sig_b


def test_token_excludes_none_values():
    sig_with_none = generate_tinkoff_token({"TerminalKey": "k", "Description": None}, "pw")
    sig_without = generate_tinkoff_token({"TerminalKey": "k"}, "pw")
    assert sig_with_none == sig_without


def test_verify_token_rejects_missing():
    assert verify_tinkoff_token({"TerminalKey": "k"}, "pw") is False


def test_verify_token_accepts_correct():
    params = {"TerminalKey": "k", "OrderId": "1"}
    token = generate_tinkoff_token(params, "pw")
    assert verify_tinkoff_token({**params, "Token": token}, "pw") is True


def test_verify_token_rejects_wrong_password():
    params = {"TerminalKey": "k", "OrderId": "1"}
    token = generate_tinkoff_token(params, "right")
    assert verify_tinkoff_token({**params, "Token": token}, "wrong") is False


def test_build_receipt_shape_for_54fz():
    receipt = build_receipt(
        description="Pro month",
        amount_kopecks=99900,
        customer_email="user@example.test",
    )
    assert receipt["Email"] == "user@example.test"
    assert receipt["Taxation"] == "usn_income"
    items = receipt["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["Amount"] == 99900
    assert item["Price"] == 99900
    assert item["Quantity"] == 1
    assert item["Tax"] == "vat22"  # НДС 22% effective 2026-01-01
    assert item["PaymentMethod"] == "full_prepayment"
    assert item["PaymentObject"] == "service"


def test_build_receipt_truncates_long_description():
    receipt = build_receipt(
        description="A" * 200, amount_kopecks=100, customer_email="x@example.test"
    )
    assert len(receipt["Items"][0]["Name"]) == 64


def test_provider_requires_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.billing.providers.tinkoff_provider.get_settings",
        lambda: type(
            "S",
            (),
            {
                "tinkoff_terminal_key": "",
                "tinkoff_password": "",
                "tinkoff_api_url": "https://test/",
            },
        )(),
    )
    provider = TinkoffProvider(terminal_key="", password="")
    with pytest.raises(ProviderUnavailableError):
        provider._require_creds()


def test_tinkoff_checkout_result_urls_tag_tinkoff_provider_for_russian_pages():
    assert _checkout_result_urls("https://wai.computer/", "tinkoff") == (
        "https://wai.computer/billing/success?provider=tinkoff&lang=ru",
        "https://wai.computer/billing/cancel?provider=tinkoff&lang=ru",
    )


def test_stripe_checkout_result_urls_use_global_billing_pages():
    assert _checkout_result_urls("https://wai.computer/", "stripe") == (
        "https://wai.computer/billing/success",
        "https://wai.computer/billing/cancel",
    )


def test_tinkoff_ack_response_is_plain_ok():
    response = _tinkoff_ack_response()
    assert response.status_code == 200
    assert response.media_type == "text/plain"
    assert response.body == b"OK"


@pytest.mark.asyncio
async def test_parse_webhook_rejects_invalid_signature():
    provider = TinkoffProvider(terminal_key="k", password="pw")
    body = json.dumps(
        {
            "TerminalKey": "k",
            "OrderId": "o1",
            "Status": "CONFIRMED",
            "Token": "definitely-wrong",
        }
    ).encode()
    with pytest.raises(ValueError, match="signature invalid"):
        await provider.parse_webhook(raw_body=body, headers={})


@pytest.mark.asyncio
async def test_parse_webhook_normalizes_status():
    provider = TinkoffProvider(terminal_key="k", password="pw")
    payload = {
        "TerminalKey": "k",
        "OrderId": "order-123",
        "Status": "CONFIRMED",
        "Amount": 99900,
        "PaymentId": "p1",
        "CustomerKey": "user-uuid",
        "RebillId": "rb-1",
    }
    token = generate_tinkoff_token(payload, "pw")
    body = json.dumps({**payload, "Token": token}).encode()

    event = await provider.parse_webhook(raw_body=body, headers={})
    assert event.type == "tinkoff.confirmed"
    assert event.status == "active"
    assert event.subscription_id_provider == "order-123"
    assert event.customer_id_provider == "user-uuid"
    assert event.raw["rebill_id"] == "rb-1"
    assert event.raw["payment_id"] == "p1"


@pytest.mark.asyncio
async def test_parse_webhook_extracts_checkout_data_period():
    provider = TinkoffProvider(terminal_key="k", password="pw")
    payload = {
        "TerminalKey": "k",
        "OrderId": "order-123",
        "Status": "CONFIRMED",
        "Amount": 799900,
        "PaymentId": "p1",
        "CustomerKey": "user-uuid",
        "RebillId": "rb-1",
        "DATA": {"user_id": "user-uuid", "plan_code": "pro", "period": "year"},
    }
    token = generate_tinkoff_token(payload, "pw")
    body = json.dumps({**payload, "Token": token}).encode()

    event = await provider.parse_webhook(raw_body=body, headers={})

    assert event.raw["plan_code"] == "pro"
    assert event.raw["period"] == "year"


@pytest.mark.asyncio
async def test_parse_webhook_accepts_title_case_data_period():
    provider = TinkoffProvider(terminal_key="k", password="pw")
    payload = {
        "TerminalKey": "k",
        "OrderId": "order-123",
        "Status": "CONFIRMED",
        "Amount": 799900,
        "PaymentId": "p1",
        "CustomerKey": "user-uuid",
        "RebillId": "rb-1",
        "Data": {"user_id": "user-uuid", "plan_code": "pro", "period": "year"},
    }
    token = generate_tinkoff_token(payload, "pw")
    body = json.dumps({**payload, "Token": token}).encode()

    event = await provider.parse_webhook(raw_body=body, headers={})

    assert event.raw["plan_code"] == "pro"
    assert event.raw["period"] == "year"


@pytest.mark.asyncio
async def test_parse_webhook_rejected_status_maps_to_past_due():
    provider = TinkoffProvider(terminal_key="k", password="pw")
    payload = {
        "TerminalKey": "k",
        "OrderId": "order-x",
        "Status": "REJECTED",
        "PaymentId": "p9",
    }
    token = generate_tinkoff_token(payload, "pw")
    body = json.dumps({**payload, "Token": token}).encode()
    event = await provider.parse_webhook(raw_body=body, headers={})
    assert event.status == "past_due"


@pytest.mark.asyncio
async def test_create_checkout_marks_parent_recurrent_payment(monkeypatch):
    provider = TinkoffProvider(terminal_key="terminal", password="pw")
    calls: list[tuple[str, dict]] = []

    async def fake_amount(*, plan_code: str, period: str) -> int:
        return 99900

    async def fake_call(method: str, payload: dict) -> dict:
        calls.append((method, payload))
        return {"Success": True, "PaymentURL": "https://pay.tbank.test/new/abc", "PaymentId": "p1"}

    monkeypatch.setattr(provider, "_resolve_amount_kopecks", fake_amount)
    monkeypatch.setattr(provider, "_call", fake_call)

    await provider.create_checkout(
        plan_code="pro",
        period="month",
        user_email="payer@example.test",
        user_id="user-uuid",
        success_url="https://wai.computer/billing/success",
        cancel_url="https://wai.computer/billing/cancel",
    )

    assert calls[0][0] == "Init"
    payload = calls[0][1]
    assert payload["PayType"] == "O"
    assert payload["SuccessURL"] == "https://wai.computer/billing/success"
    assert payload["FailURL"] == "https://wai.computer/billing/cancel"
    assert payload["Recurrent"] == "Y"
    assert payload["OperationInitiatorType"] == "1"
    assert payload["CustomerKey"] == "user-uuid"
    assert payload["DATA"] == {
        "user_id": "user-uuid",
        "plan_code": "pro",
        "period": "month",
    }
    assert verify_tinkoff_token(payload, "pw") is True


@pytest.mark.asyncio
async def test_charge_rebill_uses_mit_recurring_init(monkeypatch):
    provider = TinkoffProvider(terminal_key="terminal", password="pw")
    calls: list[tuple[str, dict]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        calls.append((method, payload))
        if method == "Init":
            return {"Success": True, "PaymentId": "payment-1"}
        return {"Success": True, "Status": "CONFIRMED"}

    monkeypatch.setattr(provider, "_call", fake_call)

    await provider.charge_rebill(
        rebill_id="rebill-1",
        amount_kopecks=99900,
        description="PRO month",
        customer_email="payer@example.test",
        user_id="user-uuid",
    )

    assert calls[0][0] == "Init"
    init_payload = calls[0][1]
    assert init_payload["PayType"] == "O"
    assert init_payload["OperationInitiatorType"] == "R"
    assert "Recurrent" not in init_payload
    assert "CustomerKey" not in init_payload
    assert verify_tinkoff_token(init_payload, "pw") is True

    assert calls[1][0] == "Charge"
    charge_payload = calls[1][1]
    assert charge_payload["RebillId"] == "rebill-1"
    assert verify_tinkoff_token(charge_payload, "pw") is True


@pytest.mark.asyncio
async def test_apply_tinkoff_confirmed_creates_pro_year_subscription(
    db_session: AsyncSession,
):
    user = User(email="tinkoff.year@example.com")
    db_session.add(user)
    await db_session.flush()

    event = ProviderEvent(
        type="tinkoff.confirmed",
        subscription_id_provider="order-year",
        customer_id_provider=str(user.id),
        status="active",
        raw={
            "order_id": "order-year",
            "status": "CONFIRMED",
            "rebill_id": "rebill-year",
            "payment_id": "payment-year",
            "amount": 799900,
            "plan_code": "pro",
            "period": "year",
            "payload": {"Status": "CONFIRMED"},
        },
    )

    await apply_tinkoff_event(db_session, event)
    await db_session.refresh(user)

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.tinkoff_rebill_id == "rebill-year")
        )
    ).scalar_one()
    plan = await db_session.get(Plan, sub.plan_id)
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.subscription_id == sub.id))
    ).scalar_one()

    assert user.current_subscription_id == sub.id
    assert plan is not None
    assert plan.code == "pro"
    assert sub.provider == "tinkoff"
    assert sub.status == "active"
    assert sub.billing_period == "year"
    assert sub.current_period_end is not None
    assert sub.tinkoff_next_charge_at is not None
    assert invoice.amount == 7999
    assert invoice.currency == "RUB"


@pytest.mark.asyncio
async def test_apply_tinkoff_rejected_initial_payment_does_not_create_subscription(
    db_session: AsyncSession,
):
    user = User(email="tinkoff.rejected@example.com")
    db_session.add(user)
    await db_session.flush()

    event = ProviderEvent(
        type="tinkoff.rejected",
        subscription_id_provider="order-rejected",
        customer_id_provider=str(user.id),
        status="past_due",
        raw={
            "order_id": "order-rejected",
            "status": "REJECTED",
            "payment_id": "payment-rejected",
            "amount": 99900,
            "plan_code": "pro",
            "period": "month",
            "payload": {"Status": "REJECTED"},
        },
    )

    await apply_tinkoff_event(db_session, event)
    await db_session.refresh(user)

    assert user.current_subscription_id is None
    assert (await db_session.execute(select(Subscription))).scalars().all() == []
    assert (await db_session.execute(select(Invoice))).scalars().all() == []


@pytest.mark.asyncio
async def test_apply_tinkoff_confirmed_updates_rebill_id_for_existing_customer(
    db_session: AsyncSession,
):
    user = User(email="tinkoff.refresh-rebill@example.com")
    db_session.add(user)
    await db_session.flush()
    plan = (await db_session.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="tinkoff",
        billing_period="month",
        tinkoff_customer_key=str(user.id),
        tinkoff_rebill_id="rebill-old",
    )
    db_session.add(sub)
    await db_session.flush()

    event = ProviderEvent(
        type="tinkoff.confirmed",
        subscription_id_provider="order-new-rebill",
        customer_id_provider=str(user.id),
        status="active",
        raw={
            "order_id": "order-new-rebill",
            "status": "CONFIRMED",
            "rebill_id": "rebill-new",
            "payment_id": "payment-new-rebill",
            "amount": 99900,
            "plan_code": "pro",
            "period": "month",
            "payload": {"Status": "CONFIRMED"},
        },
    )

    await apply_tinkoff_event(db_session, event)
    await db_session.refresh(sub)

    assert sub.tinkoff_rebill_id == "rebill-new"


@pytest.mark.asyncio
async def test_apply_tinkoff_confirmed_is_idempotent_by_payment_id(
    db_session: AsyncSession,
):
    user = User(email="tinkoff.idempotent@example.com")
    db_session.add(user)
    await db_session.flush()
    event = ProviderEvent(
        type="tinkoff.confirmed",
        subscription_id_provider="order-idempotent",
        customer_id_provider=str(user.id),
        status="active",
        raw={
            "order_id": "order-idempotent",
            "status": "CONFIRMED",
            "rebill_id": "rebill-idempotent",
            "payment_id": "payment-idempotent",
            "amount": 99900,
            "plan_code": "pro",
            "period": "month",
            "payload": {"Status": "CONFIRMED"},
        },
    )

    await apply_tinkoff_event(db_session, event)
    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.tinkoff_rebill_id == "rebill-idempotent")
        )
    ).scalar_one()
    original_period_end = sub.current_period_end

    await apply_tinkoff_event(db_session, event)
    await db_session.refresh(sub)
    invoices = (
        await db_session.execute(select(Invoice).where(Invoice.subscription_id == sub.id))
    ).scalars().all()

    assert len(invoices) == 1
    assert sub.current_period_end == original_period_end


@pytest.mark.asyncio
async def test_apply_tinkoff_confirmed_infers_year_period_from_amount(
    db_session: AsyncSession,
):
    user = User(email="tinkoff.infer-year@example.com")
    db_session.add(user)
    await db_session.flush()

    event = ProviderEvent(
        type="tinkoff.confirmed",
        subscription_id_provider="order-infer-year",
        customer_id_provider=str(user.id),
        status="active",
        raw={
            "order_id": "order-infer-year",
            "status": "CONFIRMED",
            "rebill_id": "rebill-infer-year",
            "payment_id": "payment-infer-year",
            "amount": 799900,
            "payload": {"Status": "CONFIRMED"},
        },
    )

    await apply_tinkoff_event(db_session, event)

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.tinkoff_rebill_id == "rebill-infer-year")
        )
    ).scalar_one()
    assert sub.billing_period == "year"
