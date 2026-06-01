"""Tests for best-effort Telegram ops alerts."""

import time
from types import SimpleNamespace

import app.core.ops_alerts as ops


def test_allow_throttles_per_alert_code():
    ops._last_sent.clear()
    assert ops._allow("alert.x") is True
    assert ops._allow("alert.x") is False  # throttled within window
    assert ops._allow("alert.y") is True  # different code unaffected


def test_allow_resets_after_window():
    ops._last_sent.clear()
    assert ops._allow("alert.z") is True
    ops._last_sent["alert.z"] = time.monotonic() - ops.OPS_ALERT_THROTTLE_SECONDS - 1
    assert ops._allow("alert.z") is True


def test_format_includes_message_code_and_safe_extras_only():
    text = ops._format(
        "realtime.session_mint.high_rate",
        "High mint rate",
        {
            "user_id": "u1",
            "mints_last_15min": 60,
            "transcript": "SECRET TRANSCRIPT",
            "email": "a@b.com",
        },
        "warning",
    )
    assert "High mint rate" in text
    assert "realtime.session_mint.high_rate" in text
    assert "u1" in text and "60" in text
    # Unsafe/PII keys are never forwarded.
    assert "SECRET TRANSCRIPT" not in text
    assert "a@b.com" not in text


def test_notify_ops_noop_without_chat(monkeypatch):
    monkeypatch.setattr(
        ops,
        "get_settings",
        lambda: SimpleNamespace(telegram_ops_chat_id=0, telegram_bot_token="t"),
    )

    def boom(*_a, **_k):
        raise AssertionError("must not proceed past the unconfigured guard")

    monkeypatch.setattr(ops, "_allow", boom)
    ops.notify_ops(alert_code="x", message="y")  # must be a silent no-op
