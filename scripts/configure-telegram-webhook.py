#!/usr/bin/env python3
"""Align Telegram webhook ownership with the configured Bot API endpoint.

Production uses a local telegram-bot-api service so large Telegram media can be
downloaded locally. In that mode the webhook must also be owned by the local Bot
API server; receiving updates through api.telegram.org while calling getFile on
the local server produces invalid-file errors for media messages.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import httpx

SCRIPT_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if SCRIPT_BACKEND.exists():
    sys.path.insert(0, str(SCRIPT_BACKEND))

from app.config import get_settings  # noqa: E402

CLOUD_BOT_API_BASE_URL = "https://api.telegram.org"
WEBHOOK_ALLOWED_UPDATES = ["message", "callback_query"]


class TelegramWebhookConfigError(Exception):
    """Raised when Telegram webhook alignment cannot be completed."""


def _normalize_base_url(value: str) -> str:
    clean = (value or "").strip().rstrip("/")
    return clean or CLOUD_BOT_API_BASE_URL


def _is_cloud_base_url(value: str) -> bool:
    parsed = urlsplit(_normalize_base_url(value))
    return parsed.scheme == "https" and parsed.netloc == "api.telegram.org"


def _bot_api_method_url(base_url: str, token: str, method: str) -> str:
    return f"{_normalize_base_url(base_url)}/bot{token}/{method}"


def _parse_response(method: str, response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise TelegramWebhookConfigError(
            f"Telegram {method} returned invalid JSON"
        ) from exc

    if response.status_code >= 400 or not data.get("ok"):
        description = str(data.get("description") or f"HTTP {response.status_code}")
        raise TelegramWebhookConfigError(f"Telegram {method} failed: {description}")

    result = data.get("result")
    return result if isinstance(result, dict) else {"value": result}


def _post_json(
    base_url: str,
    token: str,
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(_bot_api_method_url(base_url, token, method), json=payload)
    except httpx.HTTPError as exc:
        raise TelegramWebhookConfigError(
            f"Telegram {method} request failed: {type(exc).__name__}"
        ) from exc
    return _parse_response(method, response)


def _webhook_url(frontend_url: str) -> str:
    base = (frontend_url or "").strip().rstrip("/")
    if not base:
        raise TelegramWebhookConfigError("FRONTEND_URL is required to configure Telegram webhook")
    return f"{base}/api/telegram/webhook"


def _webhook_payload(webhook_url: str, secret_token: str) -> dict[str, Any]:
    return {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": WEBHOOK_ALLOWED_UPDATES,
        "drop_pending_updates": False,
    }


def _require_runtime_settings(token: str, secret: str) -> str | None:
    if not token and not secret:
        return "Telegram bot runtime is not configured; webhook alignment skipped."
    if not token or not secret:
        raise TelegramWebhookConfigError(
            "Telegram webhook alignment requires both TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_WEBHOOK_SECRET_TOKEN"
        )
    return None


def _runtime_settings() -> Any:
    try:
        return get_settings()
    except Exception as exc:
        telegram_env_present = any(
            os.environ.get(key)
            for key in (
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_WEBHOOK_SECRET_TOKEN",
                "TELEGRAM_BOT_API_BASE_URL",
            )
        )
        if telegram_env_present:
            raise TelegramWebhookConfigError(
                f"Could not load backend settings: {type(exc).__name__}"
            ) from exc
        return SimpleNamespace(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_webhook_secret_token=os.environ.get("TELEGRAM_WEBHOOK_SECRET_TOKEN", ""),
            telegram_bot_api_base_url=os.environ.get(
                "TELEGRAM_BOT_API_BASE_URL", CLOUD_BOT_API_BASE_URL
            ),
            frontend_url=os.environ.get("FRONTEND_URL", ""),
        )


def configure_telegram_webhook(settings: Any | None = None) -> dict[str, Any]:
    runtime = settings or _runtime_settings()
    token = str(getattr(runtime, "telegram_bot_token", "") or "").strip()
    secret = str(getattr(runtime, "telegram_webhook_secret_token", "") or "").strip()
    skip_reason = _require_runtime_settings(token, secret)
    if skip_reason is not None:
        return {"mode": "disabled", "changes": [], "message": skip_reason}

    active_base = _normalize_base_url(str(getattr(runtime, "telegram_bot_api_base_url", "") or ""))
    webhook_url = _webhook_url(str(getattr(runtime, "frontend_url", "") or ""))
    changes: list[str] = []
    mode = "cloud" if _is_cloud_base_url(active_base) else "local"

    active_info = _post_json(active_base, token, "getWebhookInfo", {})
    cloud_info = (
        active_info
        if mode == "cloud"
        else _post_json(CLOUD_BOT_API_BASE_URL, token, "getWebhookInfo", {})
    )

    if mode == "local":
        if str(cloud_info.get("url") or "").strip():
            _post_json(
                CLOUD_BOT_API_BASE_URL,
                token,
                "deleteWebhook",
                {"drop_pending_updates": False},
            )
            changes.append("cloud_delete_webhook")
            cleared_cloud_info = _post_json(
                CLOUD_BOT_API_BASE_URL, token, "getWebhookInfo", {}
            )
            if str(cleared_cloud_info.get("url") or "").strip():
                raise TelegramWebhookConfigError("Cloud Telegram webhook is still configured")
            _post_json(CLOUD_BOT_API_BASE_URL, token, "logOut", {})
            changes.append("cloud_logout")

        if str(active_info.get("url") or "").strip() != webhook_url:
            _post_json(active_base, token, "setWebhook", _webhook_payload(webhook_url, secret))
            changes.append("local_set_webhook")

        verified = _post_json(active_base, token, "getWebhookInfo", {})
        if str(verified.get("url") or "").strip() != webhook_url:
            raise TelegramWebhookConfigError("Local Telegram webhook verification failed")
    else:
        if str(active_info.get("url") or "").strip() != webhook_url:
            _post_json(active_base, token, "setWebhook", _webhook_payload(webhook_url, secret))
            changes.append("cloud_set_webhook")
        verified = _post_json(active_base, token, "getWebhookInfo", {})
        if str(verified.get("url") or "").strip() != webhook_url:
            raise TelegramWebhookConfigError("Cloud Telegram webhook verification failed")

    return {"mode": mode, "webhook_url": webhook_url, "changes": changes}


def main() -> int:
    try:
        result = configure_telegram_webhook()
    except TelegramWebhookConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
