"""Relay inbound Sentry webhooks for the CLIENT apps to the Telegram ops chat.

Backend errors already self-forward in-process via ``observability.notify_ops``.
The native/web clients report to their own per-platform Sentry projects
(``waicomputer-macos``/``-ios``/``-android``/``-web``), so this endpoint bridges
those: a Sentry internal integration POSTs issue and issue-alert webhooks here,
we verify the HMAC signature, and forward a compact, PII-safe line to the same
Telegram group within seconds.

Wiring (one-time, in Sentry): create an internal integration with this URL as
its Webhook URL, subscribe to the "issue" resource (and add it as an Alert Rule
Action for frequency-based "repeated" alerts), and put its Client Secret in
``SENTRY_WEBHOOK_SECRET``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response, status

from app.config import get_settings
from app.core.ops_alerts import notify_ops

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentry", tags=["sentry"])

# Per-platform Sentry project slug -> human label. The backend project is
# intentionally absent: it already forwards its own errors in-process, and
# relaying it here too would double-alert.
_PROJECT_APP_LABELS: dict[str, str] = {
    "waicomputer-macos": "macOS",
    "waicomputer-ios": "iOS",
    "waicomputer-android": "Android",
    "waicomputer-web": "Web",
}

# Only these webhook actions are alertable (a new problem or a regression).
# Housekeeping actions (resolved/assigned/archived/ignored) are acknowledged
# silently so they never reach the chat.
_ALERTABLE_ACTIONS = frozenset({"created", "unresolved", "triggered"})


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """True when ``signature`` is the HMAC-SHA256 of the raw body under ``secret``.

    Sentry signs every integration webhook with the integration's Client Secret
    (``Sentry-Hook-Signature`` header). Constant-time compare; verification must
    run against the RAW body, never re-serialized JSON.
    """
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def extract_alert(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the alertable fields out of an ``issue`` or ``event_alert`` webhook.

    PII-safe by construction: returns only project slug, level, error type, a
    truncated title, the seen-count, and the Sentry link — never request bodies,
    user data, or stack locals. Returns ``None`` for non-actionable payloads.
    """
    action = _str(payload.get("action"))
    if action is not None and action not in _ALERTABLE_ACTIONS:
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    issue = data.get("issue") if isinstance(data.get("issue"), dict) else None
    event = data.get("event") if isinstance(data.get("event"), dict) else None
    src = issue or event
    if src is None:
        return None

    project = None
    proj = src.get("project")
    if isinstance(proj, dict):
        project = _str(proj.get("slug")) or _str(proj.get("name"))
    project = project or _str(payload.get("project"))
    if project is None:
        return None

    metadata = src.get("metadata") if isinstance(src.get("metadata"), dict) else {}
    err_type = _str(metadata.get("type")) or _str(src.get("type")) or "Issue"
    title = (
        _str(src.get("title"))
        or _str(metadata.get("value"))
        or _str(src.get("culprit"))
        or err_type
    )
    level = (_str(src.get("level")) or "error").lower()
    count = src.get("count")
    if isinstance(count, str) and count.isdigit():
        count = int(count)  # Sentry's issue serializer emits count as a string
    if not isinstance(count, int):
        times = src.get("times_seen")
        count = times if isinstance(times, int) else None
    url = _str(src.get("web_url")) or _str(src.get("permalink"))
    if url is None and event is not None:
        url = _str(event.get("web_url"))

    return {
        "project": project,
        "type": err_type,
        "title": title[:200],
        "level": level,
        "count": count,
        "url": url,
    }


@router.post("/webhook")
async def sentry_webhook(request: Request) -> Response:
    """Receive a Sentry integration webhook and relay client-app alerts to Telegram."""
    settings = get_settings()
    secret = settings.sentry_webhook_secret
    if not secret:
        # Not configured yet (no integration Client Secret). Fail closed.
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    body = await request.body()
    signature = request.headers.get("sentry-hook-signature") or request.headers.get(
        "x-sentry-hook-signature"
    )
    if not verify_signature(secret, body, signature):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = json.loads(body)
    except ValueError:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    if not isinstance(payload, dict):
        return Response(status_code=status.HTTP_200_OK)

    info = extract_alert(payload)
    if info is None:
        return Response(status_code=status.HTTP_200_OK)

    label = _PROJECT_APP_LABELS.get(info["project"])
    if label is None:
        # Unknown / backend project — ack without alerting (avoids double-alert).
        return Response(status_code=status.HTTP_200_OK)

    count = info["count"]
    seen = f" · seen {count}×" if isinstance(count, int) and count > 1 else ""
    lines = [f"[{label}] {info['type']}: {info['title']}{seen}"]
    if info["url"]:
        lines.append(info["url"])
    level = info["level"] if info["level"] in ("error", "fatal", "warning") else "error"

    # notify_ops is throttled (1 / alert_code / 10 min), PII-safe, off-thread and
    # never raises — keyed per project+type so distinct crashes alert separately
    # while a repeating one can't flood the chat.
    notify_ops(
        alert_code=f"sentry.{info['project']}.{info['type']}",
        message="\n".join(lines),
        extras={"provider": "sentry", "error_type": info["type"]},
        level=level,
    )
    return Response(status_code=status.HTTP_200_OK)
