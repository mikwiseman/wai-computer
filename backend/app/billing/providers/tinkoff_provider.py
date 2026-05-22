"""T-Bank (Tinkoff) эквайринг provider for the RU rail.

Recurring-subscription flow:

1. Init with ``Recurrent=Y`` + ``CustomerKey`` — first checkout. User completes
   payment on the T-Bank hosted form. Webhook returns ``RebillId`` which we
   store on the subscription row.
2. Charge with ``RebillId`` — silent server-initiated renewal on each cycle
   (driven by a Celery beat task scheduled from
   ``subscription.tinkoff_next_charge_at``).
3. Cancel — set ``cancel_at_period_end`` locally; we simply stop scheduling
   the next Charge. There is no provider-side "cancel subscription" call.

Signature scheme: SHA-256 of sorted-primitive-values concatenated with the
terminal password. Receipts (54-ФЗ) follow the ``buildReceipt`` shape from
wai-pay.

Reference: https://developer.tbank.ru/eacq/api/init
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

import httpx

from app.billing.providers.base import (
    CheckoutResult,
    PaymentProvider,
    ProviderEvent,
    ProviderUnavailableError,
)
from app.config import get_settings

logger = logging.getLogger(__name__)


# Map T-Bank statuses → our normalized SubscriptionStatus values.
_STATUS_MAP = {
    "NEW": "incomplete",
    "FORM_SHOWED": "incomplete",
    "AUTHORIZING": "incomplete",
    "AUTHORIZED": "active",
    "CONFIRMING": "active",
    "CONFIRMED": "active",
    "AUTH_FAIL": "past_due",
    "REJECTED": "past_due",
    "CANCELED": "canceled",
    "REVERSED": "canceled",
    "DEADLINE_EXPIRED": "expired",
}


def _normalize_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    return _STATUS_MAP.get(raw)


def generate_tinkoff_token(params: dict[str, Any], password: str) -> str:
    """SHA-256 of sorted primitive values concatenated with the password.

    Matches wai-pay/backend/src/providers/tinkoff/signature.ts.
    """
    params_with_password = {**params, "Password": password}
    pieces: list[str] = []
    for key in sorted(params_with_password.keys()):
        value = params_with_password[key]
        if value is None:
            continue
        # Skip nested structures (Receipt, DATA, Shops, Token itself).
        if isinstance(value, (dict, list)):
            continue
        if isinstance(value, bool):
            pieces.append("true" if value else "false")
            continue
        pieces.append(str(value))
    return hashlib.sha256("".join(pieces).encode("utf-8")).hexdigest()


def verify_tinkoff_token(payload: dict[str, Any], password: str) -> bool:
    received = payload.get("Token")
    if not isinstance(received, str):
        return False
    rest = {k: v for k, v in payload.items() if k != "Token"}
    expected = generate_tinkoff_token(rest, password)
    return expected == received


def build_receipt(*, description: str, amount_kopecks: int, customer_email: str) -> dict[str, Any]:
    """54-ФЗ receipt body. НДС 22% from 2026-01-01 ('vat22')."""
    return {
        "Email": customer_email,
        "Taxation": "usn_income",  # ООО WaiWai uses УСН Доходы; adjust if entity changes.
        "Items": [
            {
                "Name": description[:64],
                "Price": amount_kopecks,
                "Quantity": 1,
                "Amount": amount_kopecks,
                "Tax": "vat22",
                "PaymentMethod": "full_prepayment",
                "PaymentObject": "service",
            }
        ],
    }


class TinkoffProvider(PaymentProvider):
    """T-Bank эквайринг with Recurrent subscription support."""

    name = "tinkoff"

    def __init__(
        self,
        terminal_key: str | None = None,
        password: str | None = None,
        api_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self._terminal_key = terminal_key or settings.tinkoff_terminal_key
        self._password = password or settings.tinkoff_password
        self._api_url = (api_url or settings.tinkoff_api_url).rstrip("/") + "/"

    def _require_creds(self) -> tuple[str, str]:
        if not self._terminal_key or not self._password:
            raise ProviderUnavailableError("Tinkoff terminal credentials not configured")
        return self._terminal_key, self._password

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self._api_url}{method}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        text = r.text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Tinkoff {method}: non-JSON response HTTP {r.status_code}: {text[:300]}"
            ) from exc
        if r.status_code >= 400:
            raise RuntimeError(f"Tinkoff {method}: HTTP {r.status_code} body={parsed}")
        return parsed

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
        terminal_key, password = self._require_creds()
        amount_kopecks = await self._resolve_amount_kopecks(plan_code=plan_code, period=period)

        # OrderId: deterministic per (user, plan, period) start. Use a UUID so
        # we don't collide across retries; we store it on the BillingEvent.
        from uuid import uuid4

        order_id = uuid4().hex

        base = {
            "TerminalKey": terminal_key,
            "Amount": amount_kopecks,
            "OrderId": order_id,
            "PayType": "O",
            "Description": f"{plan_code.upper()} {period}"[:64],
            "CustomerKey": user_id,
            "Recurrent": "Y",
            "OperationInitiatorType": "1",
            "Language": "ru",
            "SuccessURL": success_url,
            "FailURL": cancel_url,
            "NotificationURL": _notification_url(),
            "DATA": {"user_id": user_id, "plan_code": plan_code, "period": period},
        }
        token = generate_tinkoff_token(base, password)
        payload = {
            **base,
            "Token": token,
            "Receipt": build_receipt(
                description=f"{plan_code.upper()} {period}",
                amount_kopecks=amount_kopecks,
                customer_email=user_email,
            ),
        }

        response = await self._call("Init", payload)
        if not response.get("Success"):
            raise RuntimeError(
                f"Tinkoff Init failed: {response.get('Message') or response.get('ErrorCode')}"
            )
        payment_url = response.get("PaymentURL")
        payment_id = response.get("PaymentId")
        if not payment_url or not payment_id:
            raise RuntimeError("Tinkoff Init returned no PaymentURL / PaymentId")

        return CheckoutResult(
            checkout_url=payment_url,
            provider=self.name,
            provider_session_id=str(payment_id),
            provider_order_id=order_id,
        )

    async def charge_rebill(
        self,
        *,
        rebill_id: str,
        amount_kopecks: int,
        description: str,
        customer_email: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Server-initiated charge using a previously stored RebillId."""
        terminal_key, password = self._require_creds()
        from uuid import uuid4

        order_id = uuid4().hex
        # Step 1: Init for the new charge cycle (still recurrent=Y so we keep the chain).
        init_base = {
            "TerminalKey": terminal_key,
            "Amount": amount_kopecks,
            "OrderId": order_id,
            "PayType": "O",
            "Description": description[:64],
            "OperationInitiatorType": "R",
            "NotificationURL": _notification_url(),
        }
        init_token = generate_tinkoff_token(init_base, password)
        init_response = await self._call(
            "Init",
            {
                **init_base,
                "Token": init_token,
                "Receipt": build_receipt(
                    description=description,
                    amount_kopecks=amount_kopecks,
                    customer_email=customer_email,
                ),
            },
        )
        if not init_response.get("Success") or not init_response.get("PaymentId"):
            raise RuntimeError(f"Tinkoff Init (rebill cycle) failed: {init_response}")

        # Step 2: Charge using the stored RebillId.
        charge_base = {
            "TerminalKey": terminal_key,
            "PaymentId": init_response["PaymentId"],
            "RebillId": rebill_id,
        }
        charge_token = generate_tinkoff_token(charge_base, password)
        charge_response = await self._call("Charge", {**charge_base, "Token": charge_token})
        if not charge_response.get("Success"):
            raise RuntimeError(f"Tinkoff Charge failed: {charge_response}")
        return charge_response

    async def cancel_subscription(self, provider_subscription_id: str) -> None:
        """No-op for T-Bank: cancel happens by ceasing to schedule the next Charge."""
        return None

    async def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> ProviderEvent:
        _, password = self._require_creds()
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Tinkoff webhook body not JSON") from exc
        if not verify_tinkoff_token(payload, password):
            raise ValueError("Tinkoff webhook signature invalid")

        order_id = str(payload.get("OrderId") or "")
        status = str(payload.get("Status") or "")
        rebill_id = payload.get("RebillId")
        customer_key = payload.get("CustomerKey")
        data = payload.get("Data")
        if not isinstance(data, dict):
            data = payload.get("DATA")
        if not isinstance(data, dict):
            data = {}

        plan_code = data.get("plan_code")
        period = data.get("period")
        return ProviderEvent(
            type=f"tinkoff.{status.lower() or 'unknown'}",
            subscription_id_provider=order_id,  # we key by OrderId on our side
            customer_id_provider=str(customer_key) if customer_key else None,
            status=_normalize_status(status),
            raw={
                "order_id": order_id,
                "status": status,
                "rebill_id": str(rebill_id) if rebill_id is not None else None,
                "payment_id": str(payload.get("PaymentId") or ""),
                "amount": payload.get("Amount"),
                "plan_code": str(plan_code).strip().lower() if plan_code else None,
                "period": str(period).strip().lower() if period else None,
                "payload": payload,
            },
        )

    async def _resolve_amount_kopecks(self, *, plan_code: str, period: str) -> int:
        """Read the RUB amount from billing_plans, convert rubles → kopecks."""
        from sqlalchemy import select

        from app.db.session import get_db_context
        from app.models.billing import Plan

        async with get_db_context() as db:
            plan = (
                await db.execute(select(Plan).where(Plan.code == plan_code))
            ).scalar_one_or_none()
        if plan is None:
            raise ValueError(f"Plan '{plan_code}' not found")
        amount_rub = (
            plan.tinkoff_amount_rub_yearly if period == "year" else plan.tinkoff_amount_rub_monthly
        )
        if amount_rub is None or amount_rub <= 0:
            raise ValueError(f"Plan '{plan_code}' has no RUB amount for period '{period}'")
        return int(Decimal(amount_rub) * 100)


def _notification_url() -> str:
    settings = get_settings()
    base = settings.frontend_url.rstrip("/")
    return f"{base}/api/webhooks/tinkoff"
