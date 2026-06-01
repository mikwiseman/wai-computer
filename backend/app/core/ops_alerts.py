"""Best-effort operational alerts to a Telegram ops chat.

Surfaces alertable anomalies (runaway usage, repeated errors, things worth
attention) to a Telegram chat so an operator sees them within seconds instead
of via a billing dashboard hours later.

Design:
- Throttled per ``alert_code`` (one message / 10 min) so a recurring anomaly
  can't flood the chat (alert fatigue).
- Best-effort: never raises into the caller and sends off-thread, so an alert
  failure can never affect request handling.
- PII-safe: only a curated allow-list of extra fields is forwarded (matches the
  already-sanitized Sentry anomaly extras); no transcripts/emails/tokens.
"""

from __future__ import annotations

import html
import logging
import threading
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

OPS_ALERT_THROTTLE_SECONDS = 600  # one alert per alert_code per 10 minutes

# Only these extra keys are forwarded to the chat (everything else is dropped).
_SAFE_EXTRA_KEYS = frozenset(
    {
        "purpose",
        "user_id",
        "status_code",
        "mints_last_15min",
        "mints_15min",
        "count",
        "count_in_hour",
        "threshold",
        "latency_ms",
        "slow_threshold_ms",
        "audio_duration_seconds",
        "segment_count",
        "channels",
        "content_type",
        "model",
        "provider",
        "error_type",
        "recording_id",
        "transaction",
    }
)

_last_sent: dict[str, float] = {}
_throttle_lock = threading.Lock()


def _allow(alert_code: str) -> bool:
    """Return True at most once per throttle window for a given alert_code."""
    now = time.monotonic()
    with _throttle_lock:
        if now - _last_sent.get(alert_code, 0.0) < OPS_ALERT_THROTTLE_SECONDS:
            return False
        _last_sent[alert_code] = now
        return True


def _format(alert_code: str, message: str, extras: dict[str, Any] | None, level: str) -> str:
    icon = {"error": "🔴", "fatal": "🔴", "warning": "🟠"}.get(level, "ℹ️")
    lines = [f"{icon} <b>{html.escape(message)}</b>", f"<code>{html.escape(alert_code)}</code>"]
    for key in sorted(extras or {}):
        if key in _SAFE_EXTRA_KEYS:
            lines.append(f"{html.escape(key)}: <code>{html.escape(str(extras[key]))}</code>")
    return "\n".join(lines)


def _send(token: str, chat_id: int, text: str, alert_code: str) -> None:
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=8.0,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort alerting
        logger.warning(
            "ops telegram alert failed alert_code=%s error_type=%s",
            alert_code,
            type(exc).__name__,
        )


def notify_ops(
    *,
    alert_code: str,
    message: str,
    extras: dict[str, Any] | None = None,
    level: str = "warning",
) -> None:
    """Send a throttled, best-effort ops alert to the Telegram ops chat.

    No-op when no ops chat / bot token is configured. Never raises; the network
    send runs on a daemon thread so it cannot block the caller.
    """
    try:
        settings = get_settings()
        chat_id = int(getattr(settings, "telegram_ops_chat_id", 0) or 0)
        token = settings.telegram_bot_token
        if not chat_id or not token:
            return
        if not _allow(alert_code):
            return
        text = _format(alert_code, message, extras, level)
        threading.Thread(
            target=_send, args=(token, chat_id, text, alert_code), daemon=True
        ).start()
    except Exception as exc:  # noqa: BLE001 - alerting must never break callers
        logger.warning(
            "notify_ops failed alert_code=%s error_type=%s", alert_code, type(exc).__name__
        )
