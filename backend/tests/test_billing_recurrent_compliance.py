"""T-Bank recurrent-payment compliance: consent capture, RU scope, notifications."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.providers.base import CheckoutResult, ProviderEvent
from app.billing.service import apply_tinkoff_event
from app.models.billing import BillingEvent, Plan, Subscription, SubscriptionStatus
from app.models.user import User
from app.tasks.billing_renewals import (
    charge_tinkoff_subscription,
    send_due_renewal_reminders,
)
from tests.conftest import LEGAL_ACCEPTANCE


class _BillingSettings:
    frontend_url = "https://wai.computer"
    tinkoff_api_url = "https://securepay.tinkoff.ru/v2/"
    tinkoff_terminal_key = "terminal"
    tinkoff_password = "pw"
    stripe_secret_key = "sk_test"
    stripe_webhook_secret = "whsec"
    stripe_automatic_tax = False
    billing_enforcement_enabled = False
    billing_default_region = "global"


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
    )
    assert resp.status_code == 200
    return f"Bearer {resp.json()['access_token']}"


async def _ru_user(client: AsyncClient, db: AsyncSession, email: str) -> tuple[str, User]:
    bearer = await _register(client, email)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    user.region = "ru"
    user.default_language = "en"
    await db.flush()
    return bearer, user


async def _pro_plan(db: AsyncSession) -> Plan:
    return (await db.execute(select(Plan).where(Plan.code == "pro"))).scalar_one()


def _email_settings() -> MagicMock:
    settings = MagicMock()
    settings.resend_api_key = "re_test"
    settings.frontend_url = "https://wai.computer"
    settings.email_from = "WaiComputer <noreply@mail.waiwai.is>"
    return settings


# --------------------------------------------------------------------------
# Checkout: server-side RU scope + recurrent consent
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tinkoff_checkout_requires_recurring_consent(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingSettings())
    bearer, _ = await _ru_user(client, db_session, "consent.required@example.com")
    resp = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": bearer},
        json={"plan": "pro", "period": "month"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Recurring payment consent is required"


@pytest.mark.asyncio
async def test_tinkoff_override_blocked_for_non_ru_region(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingSettings())
    # region stays "global"; overriding provider=tinkoff must be rejected.
    bearer = await _register(client, "global.tinkoff@example.com")
    resp = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": bearer},
        json={
            "plan": "pro",
            "period": "month",
            "provider": "tinkoff",
            "accepted_recurring_terms": True,
        },
    )
    assert resp.status_code == 403
    assert "RU region" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_tinkoff_checkout_records_consent_event(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.billing.router.get_settings", lambda: _BillingSettings())

    class FakeTinkoff:
        async def create_checkout(self, **kwargs: object) -> CheckoutResult:
            return CheckoutResult(
                provider="tinkoff",
                checkout_url="https://pay.tbank.test/s",
                provider_session_id="pay-1",
                provider_order_id="order-consent",
            )

    monkeypatch.setattr("app.billing.router.TinkoffProvider", FakeTinkoff)
    bearer, _ = await _ru_user(client, db_session, "consent.recorded@example.com")

    resp = await client.post(
        "/api/billing/checkout",
        headers={"Authorization": bearer},
        json={"plan": "pro", "period": "year", "accepted_recurring_terms": True},
    )
    assert resp.status_code == 200

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.tinkoff_order_id == "order-consent")
        )
    ).scalar_one()
    event = (
        await db_session.execute(
            select(BillingEvent).where(
                BillingEvent.subscription_id == sub.id,
                BillingEvent.type == "recurrent_consent_accepted",
            )
        )
    ).scalar_one()
    assert event.payload["period"] == "year"
    assert event.payload["amount_rub"] == 7999.0
    assert event.payload["locale"] == "ru"
    assert event.payload["version"]


# --------------------------------------------------------------------------
# Email module content + best-effort behaviour
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_confirmation_email_ru_content() -> None:
    with patch("app.core.email.get_settings", return_value=_email_settings()), patch(
        "app.core.email.resend"
    ) as mock_resend:
        from app.core.email import send_charge_confirmation_email

        ok = await send_charge_confirmation_email(
            "user@example.com",
            amount=Decimal("999.00"),
            currency="RUB",
            period="month",
            next_charge_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            locale="ru",
        )
        assert ok is True
        args = mock_resend.Emails.send.call_args[0][0]
        assert args["subject"] == "Оплата подписки WaiComputer"
        assert "999 ₽" in args["html"]
        assert "ежемесячно" in args["html"]
        assert "01.07.2026" in args["html"]
        assert "https://wai.computer/ru/billing" in args["html"]
        assert "Управление подпиской" in args["html"]


@pytest.mark.asyncio
async def test_charge_confirmation_email_best_effort_swallows_failure() -> None:
    with patch("app.core.email.get_settings", return_value=_email_settings()), patch(
        "app.core.email.resend"
    ) as mock_resend:
        mock_resend.Emails.send.side_effect = Exception("resend down")
        from app.core.email import send_charge_confirmation_email

        ok = await send_charge_confirmation_email(
            "user@example.com",
            amount=Decimal("999.00"),
            currency="RUB",
            period="month",
            next_charge_at=None,
            locale="ru",
        )
        assert ok is False  # never raises into the charge flow


@pytest.mark.asyncio
async def test_payment_failed_email_content() -> None:
    with patch("app.core.email.get_settings", return_value=_email_settings()), patch(
        "app.core.email.resend"
    ) as mock_resend:
        from app.core.email import send_payment_failed_email

        ok = await send_payment_failed_email("user@example.com", locale="ru")
        assert ok is True
        args = mock_resend.Emails.send.call_args[0][0]
        assert args["subject"] == "Не удалось списать оплату WaiComputer"
        assert "https://wai.computer/ru/billing" in args["html"]


@pytest.mark.asyncio
async def test_renewal_reminder_email_content_en() -> None:
    with patch("app.core.email.get_settings", return_value=_email_settings()), patch(
        "app.core.email.resend"
    ) as mock_resend:
        from app.core.email import send_renewal_reminder_email

        ok = await send_renewal_reminder_email(
            "user@example.com",
            amount=Decimal("12.00"),
            currency="USD",
            next_charge_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            locale="en",
        )
        assert ok is True
        args = mock_resend.Emails.send.call_args[0][0]
        assert args["subject"] == "Your WaiComputer subscription renews soon"
        assert "$12.00" in args["html"]
        assert "Jul 01, 2026" in args["html"]
        assert "https://wai.computer/billing" in args["html"]


# --------------------------------------------------------------------------
# Charge → email wiring (covers first payment AND renewals)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_tinkoff_event_sends_charge_email_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, user = await _ru_user(client, db_session, "charge.email@example.com")
    plan = await _pro_plan(db_session)
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.INCOMPLETE.value,
        provider="tinkoff",
        billing_period="month",
        cancel_at_period_end=False,
        tinkoff_customer_key=str(user.id),
        tinkoff_rebill_id="rebill-charge",
    )
    db_session.add(sub)
    await db_session.flush()
    user.current_subscription_id = sub.id
    await db_session.flush()

    spy = AsyncMock(return_value=True)
    monkeypatch.setattr("app.billing.service.send_charge_confirmation_email", spy)

    def make_event(payment_id: str) -> ProviderEvent:
        return ProviderEvent(
            type="tinkoff.confirmed",
            subscription_id_provider="order-charge",
            customer_id_provider=str(user.id),
            status="active",
            raw={
                "order_id": "order-charge",
                "status": "CONFIRMED",
                "rebill_id": "rebill-charge",
                "payment_id": payment_id,
                "amount": 99900,
                "plan_code": "pro",
                "period": "month",
                "promo_code_id": None,
                "payload": {},
            },
        )

    await apply_tinkoff_event(db_session, make_event("pay-1"))
    await apply_tinkoff_event(db_session, make_event("pay-1"))  # duplicate → no 2nd email

    assert spy.await_count == 1
    assert spy.await_args.args[0] == user.email
    kwargs = spy.await_args.kwargs
    assert kwargs["amount"] == Decimal("999.00")
    assert kwargs["currency"] == "RUB"
    assert kwargs["period"] == "month"
    assert kwargs["locale"] == user.default_language


# --------------------------------------------------------------------------
# Renewal failure → dunning email
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renewal_failure_sends_payment_failed_email(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, user = await _ru_user(client, db_session, "renewal.fail@example.com")
    plan = await _pro_plan(db_session)
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE.value,
        provider="tinkoff",
        billing_period="month",
        cancel_at_period_end=False,
        tinkoff_rebill_id="rebill-fail",
        tinkoff_next_charge_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)
    await db_session.flush()

    class FailingProvider:
        async def charge_rebill(self, **kwargs: object) -> dict:
            raise RuntimeError("Charge blocked")

    spy = AsyncMock(return_value=True)
    monkeypatch.setattr("app.tasks.billing_renewals.send_payment_failed_email", spy)

    result = await charge_tinkoff_subscription(
        db_session, sub, plan, user, FailingProvider()
    )
    assert result == "failed"
    assert sub.status == SubscriptionStatus.PAST_DUE.value
    assert sub.tinkoff_next_charge_at is None
    spy.assert_awaited_once()
    assert spy.await_args.args[0] == user.email
    assert spy.await_args.kwargs["locale"] == user.default_language


# --------------------------------------------------------------------------
# Pre-charge renewal reminders (send once per cycle)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renewal_reminders_email_and_dedupe(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, user = await _ru_user(client, db_session, "reminder@example.com")
    plan = await _pro_plan(db_session)
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE.value,
        provider="tinkoff",
        billing_period="month",
        cancel_at_period_end=False,
        tinkoff_rebill_id="rebill-remind",
        tinkoff_next_charge_at=datetime.now(timezone.utc) + timedelta(days=3, hours=2),
    )
    db_session.add(sub)
    await db_session.flush()

    spy = AsyncMock(return_value=True)
    monkeypatch.setattr("app.tasks.billing_renewals.send_renewal_reminder_email", spy)

    first = await send_due_renewal_reminders(db_session=db_session)
    assert first == {"reminded": 1}
    spy.assert_awaited_once()
    assert spy.await_args.kwargs["locale"] == user.default_language
    markers = (
        await db_session.execute(
            select(BillingEvent).where(
                BillingEvent.subscription_id == sub.id,
                BillingEvent.type == "renewal_reminder_sent",
            )
        )
    ).scalars().all()
    assert len(markers) == 1

    second = await send_due_renewal_reminders(db_session=db_session)
    assert second == {"reminded": 0}
    spy.assert_awaited_once()  # not emailed twice for the same cycle


@pytest.mark.asyncio
async def test_send_due_renewal_reminders_uses_db_context(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, user = await _ru_user(client, db_session, "reminder.ctx@example.com")
    plan = await _pro_plan(db_session)
    sub = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE.value,
        provider="tinkoff",
        billing_period="month",
        cancel_at_period_end=False,
        tinkoff_rebill_id="rebill-ctx",
        tinkoff_next_charge_at=datetime.now(timezone.utc) + timedelta(days=3, hours=2),
    )
    db_session.add(sub)
    await db_session.flush()

    class SessionContext:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(
        "app.tasks.billing_renewals.get_db_context", lambda: SessionContext()
    )
    spy = AsyncMock(return_value=True)
    monkeypatch.setattr("app.tasks.billing_renewals.send_renewal_reminder_email", spy)

    # No db_session passed → exercises the get_db_context() branch.
    result = await send_due_renewal_reminders()
    assert result == {"reminded": 1}
    spy.assert_awaited_once()
    assert spy.await_args.kwargs["locale"] == user.default_language


def test_renewal_reminder_celery_task_runs_async_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bool] = {}

    async def fake_send_due_renewal_reminders() -> dict[str, int]:
        captured["called"] = True
        return {"reminded": 3}

    monkeypatch.setattr(
        "app.tasks.billing_renewals.send_due_renewal_reminders",
        fake_send_due_renewal_reminders,
    )
    from app.tasks.billing_renewals import send_due_renewal_reminders_task

    result = send_due_renewal_reminders_task.run()
    assert captured == {"called": True}
    assert result == {"reminded": 3}
