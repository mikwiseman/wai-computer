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


def test_send_posts_to_telegram_and_swallows_errors(monkeypatch):
    posted = {}

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(ops.httpx, "post", fake_post)
    ops._send("tok123", 42, "hello", "alert.code")
    assert "bottok123/sendMessage" in posted["url"]
    assert posted["json"]["chat_id"] == 42
    assert posted["json"]["text"] == "hello"
    assert posted["json"]["parse_mode"] == "HTML"

    # a transport error is swallowed (best-effort; never raises into the caller)
    def boom_post(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(ops.httpx, "post", boom_post)
    ops._send("tok", 1, "x", "code")  # must not raise


def test_notify_ops_dispatches_send_when_configured(monkeypatch):
    ops._last_sent.clear()
    monkeypatch.setattr(
        ops,
        "get_settings",
        lambda: SimpleNamespace(telegram_ops_chat_id=99, telegram_bot_token="tok"),
    )
    captured = {}

    class _ImmediateThread:
        def __init__(self, target, args, daemon):
            self._target = target
            self._args = args

        def start(self):
            captured["args"] = self._args
            self._target(*self._args)  # run inline so we can assert

    sent = {}
    monkeypatch.setattr(ops.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(ops, "_send", lambda *a: sent.setdefault("called", a))

    ops.notify_ops(
        alert_code="recording.processing.failed",
        message="boom",
        extras={"recording_id": "r1"},
        level="error",
    )
    # token + chat_id threaded through to _send
    assert sent["called"][0] == "tok"
    assert sent["called"][1] == 99
    assert "boom" in sent["called"][2]


def test_notify_ops_throttles_repeat_codes(monkeypatch):
    ops._last_sent.clear()
    monkeypatch.setattr(
        ops,
        "get_settings",
        lambda: SimpleNamespace(telegram_ops_chat_id=99, telegram_bot_token="tok"),
    )
    calls = []

    class _NoopThread:
        def __init__(self, target, args, daemon):
            pass

        def start(self):
            calls.append(1)

    monkeypatch.setattr(ops.threading, "Thread", _NoopThread)
    ops.notify_ops(alert_code="dup.code", message="m")
    ops.notify_ops(alert_code="dup.code", message="m")  # throttled -> no 2nd dispatch
    assert len(calls) == 1
