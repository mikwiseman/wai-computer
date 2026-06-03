"""Tests for the Sentry -> Telegram client-app alert relay."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.sentry_webhook import extract_alert, verify_signature
from app.main import app

SECRET = "test-client-secret"


@pytest_asyncio.fixture
async def webhook_client():
    """A DB-less ASGI client — the relay route has no database dependency, so we
    avoid conftest's Postgres-backed `client` fixture entirely."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _issue_payload(slug: str = "waicomputer-macos", action: str = "created", **issue) -> dict:
    base = {
        "id": "123",
        "title": "NSInvalidArgumentException: -[__NSCFString length]",
        "level": "error",
        "metadata": {"type": "NSInvalidArgumentException", "value": "-[__NSCFString length]"},
        "project": {"slug": slug, "name": "WaiComputer"},
        "web_url": "https://waiwai-diy.sentry.io/issues/123/",
    }
    base.update(issue)
    return {"action": action, "data": {"issue": base}, "installation": {"uuid": "abc"}}


# --- pure helpers -----------------------------------------------------------

def test_verify_signature_accepts_valid_and_rejects_tampered():
    body = b'{"hello":"world"}'
    sig = _sign(body)
    assert verify_signature(SECRET, body, sig) is True
    assert verify_signature(SECRET, body, sig[:-1] + ("0" if sig[-1] != "0" else "1")) is False
    assert verify_signature(SECRET, b'{"hello":"mutated"}', sig) is False
    assert verify_signature("", body, sig) is False
    assert verify_signature(SECRET, body, None) is False


def test_extract_alert_pulls_pii_safe_fields():
    info = extract_alert(_issue_payload(count="7"))
    assert info["project"] == "waicomputer-macos"
    assert info["type"] == "NSInvalidArgumentException"
    assert info["count"] == 7  # string count coerced to int
    assert info["url"] == "https://waiwai-diy.sentry.io/issues/123/"


def test_extract_alert_skips_housekeeping_actions():
    assert extract_alert(_issue_payload(action="resolved")) is None
    assert extract_alert(_issue_payload(action="assigned")) is None


def test_extract_alert_allows_regression():
    assert extract_alert(_issue_payload(action="unresolved")) is not None


# --- route ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_503_when_secret_unset(webhook_client):
    body = json.dumps(_issue_payload()).encode()
    with patch(
        "app.api.routes.sentry_webhook.get_settings",
        return_value=SimpleNamespace(sentry_webhook_secret=""),
    ):
        resp = await webhook_client.post(
            "/api/sentry/webhook", content=body, headers={"Sentry-Hook-Signature": _sign(body)}
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_webhook_401_on_bad_signature(webhook_client):
    body = json.dumps(_issue_payload()).encode()
    with patch(
        "app.api.routes.sentry_webhook.get_settings",
        return_value=SimpleNamespace(sentry_webhook_secret=SECRET),
    ), patch("app.api.routes.sentry_webhook.notify_ops") as mock_notify:
        resp = await webhook_client.post(
            "/api/sentry/webhook", content=body, headers={"Sentry-Hook-Signature": "deadbeef"}
        )
    assert resp.status_code == 401
    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_forwards_client_issue_to_telegram(webhook_client):
    body = json.dumps(_issue_payload(slug="waicomputer-android", count="12")).encode()
    with patch(
        "app.api.routes.sentry_webhook.get_settings",
        return_value=SimpleNamespace(sentry_webhook_secret=SECRET),
    ), patch("app.api.routes.sentry_webhook.notify_ops") as mock_notify:
        resp = await webhook_client.post(
            "/api/sentry/webhook", content=body, headers={"Sentry-Hook-Signature": _sign(body)}
        )
    assert resp.status_code == 200
    mock_notify.assert_called_once()
    kwargs = mock_notify.call_args.kwargs
    assert kwargs["message"].startswith("[Android] NSInvalidArgumentException:")
    assert "seen 12×" in kwargs["message"]
    assert "https://waiwai-diy.sentry.io/issues/123/" in kwargs["message"]
    assert kwargs["alert_code"] == "sentry.waicomputer-android.NSInvalidArgumentException"


@pytest.mark.asyncio
async def test_webhook_ignores_backend_and_unknown_projects(webhook_client):
    for slug in (
        "waicomputer-backend",
        "some-other-project",
    ):
        body = json.dumps(_issue_payload(slug=slug)).encode()
        with patch(
            "app.api.routes.sentry_webhook.get_settings",
            return_value=SimpleNamespace(sentry_webhook_secret=SECRET),
        ), patch("app.api.routes.sentry_webhook.notify_ops") as mock_notify:
            resp = await webhook_client.post(
                "/api/sentry/webhook", content=body, headers={"Sentry-Hook-Signature": _sign(body)}
            )
        assert resp.status_code == 200
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_acks_housekeeping_without_alerting(webhook_client):
    body = json.dumps(_issue_payload(action="resolved")).encode()
    with patch(
        "app.api.routes.sentry_webhook.get_settings",
        return_value=SimpleNamespace(sentry_webhook_secret=SECRET),
    ), patch("app.api.routes.sentry_webhook.notify_ops") as mock_notify:
        resp = await webhook_client.post(
            "/api/sentry/webhook", content=body, headers={"Sentry-Hook-Signature": _sign(body)}
        )
    assert resp.status_code == 200
    mock_notify.assert_not_called()
