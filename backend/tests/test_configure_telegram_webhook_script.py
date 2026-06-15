"""Tests for the production Telegram webhook alignment helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "configure-telegram-webhook.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("configure_telegram_webhook", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _settings(**overrides):
    base = {
        "telegram_bot_token": "123456:ABC-SECRET",
        "telegram_webhook_secret_token": "webhook-secret",
        "telegram_bot_api_base_url": "http://telegram-bot-api:8081",
        "frontend_url": "https://wai.computer",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_configure_local_webhook_logs_out_cloud_before_setting_local(monkeypatch):
    script = _load_script()
    calls: list[tuple[str, str, dict]] = []
    webhook_infos = {
        ("http://telegram-bot-api:8081", "getWebhookInfo"): {"url": ""},
        ("https://api.telegram.org", "getWebhookInfo"): {
            "url": "https://wai.computer/api/telegram/webhook"
        },
    }

    def fake_post(base_url: str, token: str, method: str, payload: dict):
        assert token == "123456:ABC-SECRET"
        calls.append((base_url, method, payload))
        if method == "getWebhookInfo":
            return webhook_infos[(base_url, method)]
        if method == "deleteWebhook":
            webhook_infos[("https://api.telegram.org", "getWebhookInfo")] = {"url": ""}
            return {"value": True}
        if method == "logOut":
            return {"value": True}
        if method == "setWebhook":
            webhook_infos[(base_url, "getWebhookInfo")] = {"url": payload["url"]}
            return {"value": True}
        raise AssertionError(method)

    monkeypatch.setattr(script, "_post_json", fake_post)

    result = script.configure_telegram_webhook(_settings())

    assert result["mode"] == "local"
    assert result["webhook_url"] == "https://wai.computer/api/telegram/webhook"
    assert [call[1] for call in calls] == [
        "getWebhookInfo",
        "getWebhookInfo",
        "deleteWebhook",
        "getWebhookInfo",
        "logOut",
        "setWebhook",
        "getWebhookInfo",
    ]
    set_payload = calls[5][2]
    assert set_payload["secret_token"] == "webhook-secret"
    assert set_payload["allowed_updates"] == ["message", "callback_query"]
    assert set_payload["drop_pending_updates"] is False


def test_configure_local_webhook_is_noop_when_already_aligned(monkeypatch):
    script = _load_script()
    calls: list[tuple[str, str, dict]] = []

    def fake_post(base_url: str, token: str, method: str, payload: dict):
        calls.append((base_url, method, payload))
        assert method == "getWebhookInfo"
        if base_url == "http://telegram-bot-api:8081":
            return {"url": "https://wai.computer/api/telegram/webhook"}
        return {"url": ""}

    monkeypatch.setattr(script, "_post_json", fake_post)

    result = script.configure_telegram_webhook(_settings())

    assert result["mode"] == "local"
    assert result["changes"] == []
    assert [call[1] for call in calls] == [
        "getWebhookInfo",
        "getWebhookInfo",
        "getWebhookInfo",
    ]


def test_configure_webhook_requires_complete_runtime_settings(monkeypatch):
    script = _load_script()

    monkeypatch.setattr(
        script,
        "_post_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )

    result = script.configure_telegram_webhook(
        _settings(telegram_bot_token="", telegram_webhook_secret_token="")
    )
    assert result["mode"] == "disabled"

    try:
        script.configure_telegram_webhook(_settings(telegram_webhook_secret_token=""))
    except script.TelegramWebhookConfigError as exc:
        assert "both TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET_TOKEN" in str(exc)
    else:
        raise AssertionError("expected TelegramWebhookConfigError")
