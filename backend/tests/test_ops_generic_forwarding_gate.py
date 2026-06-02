"""The per-event generic-error -> Telegram relay must be OFF by default.

Forwarding every uncaught error per-event floods the human ops group (and the
throttle is per-process, so it fans out across api + each celery worker). The
group gets deliberately-flagged anomalies instead; deduplicated per-issue crash
alerts arrive via the Sentry integration webhook. OPS_FORWARD_GENERIC_ERRORS=1
re-enables the raw relay.
"""

from unittest.mock import patch

from app.core.observability import _forward_generic_event_to_ops

_EVENT = {
    "level": "error",
    "exception": {"values": [{"type": "ValueError", "value": "boom"}]},
}


def test_generic_forwarding_off_by_default(monkeypatch):
    monkeypatch.delenv("OPS_FORWARD_GENERIC_ERRORS", raising=False)
    with patch("app.core.ops_alerts.notify_ops") as mock_notify:
        _forward_generic_event_to_ops(_EVENT)
    mock_notify.assert_not_called()


def test_generic_forwarding_on_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("OPS_FORWARD_GENERIC_ERRORS", "1")
    with patch("app.core.ops_alerts.notify_ops") as mock_notify:
        _forward_generic_event_to_ops(_EVENT)
    mock_notify.assert_called_once()
