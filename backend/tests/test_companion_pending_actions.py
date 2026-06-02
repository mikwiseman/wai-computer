"""P0 foundations: the additive companion SSE events, the capability-gated
emit filter, and the companion_pending_actions model registration."""

import json

from app.api.routes import companion as companion_route
from app.core.companion import (
    ActionProposedEvent,
    ActionResultEvent,
    DesktopActionEvent,
    DoneEvent,
    MemoryUpdatedEvent,
    NarrationEvent,
)
from app.models import CompanionPendingAction


def _frame(event):
    raw = companion_route._sse_format(event).decode("utf-8")
    assert raw.endswith("\n\n")
    head, body = raw.strip().split("\n", 1)
    assert head.startswith("event: ")
    assert body.startswith("data: ")
    return head[len("event: "):], json.loads(body[len("data: "):])


def test_action_proposed_event_serializes_additively():
    etype, data = _frame(
        ActionProposedEvent(
            action_id="a1",
            kind="send",
            tool="send_message_telegram",
            preview="Send to Anna: running late",
            expires_at="2026-06-01T14:05:00Z",
            recipient="Anna",
        )
    )
    assert etype == "action_proposed"
    assert "type" not in data  # popped by _sse_format
    assert data["action_id"] == "a1"
    assert data["recipient"] == "Anna"
    assert data["kind"] == "send"


def test_action_result_narration_desktop_events_serialize():
    assert _frame(
        ActionResultEvent(action_id="a1", status="executed", detail="ok")
    )[0] == "action_result"
    assert _frame(NarrationEvent(text="Opening Mail…"))[0] == "narration"
    etype, data = _frame(
        DesktopActionEvent(
            action_id="d1",
            command={"op": "open_app", "name": "Mail"},
            device_target="mac-1",
        )
    )
    assert etype == "desktop_action"
    assert data["command"] == {"op": "open_app", "name": "Mail"}
    assert data["device_target"] == "mac-1"


def test_gated_events_withheld_without_capability():
    # No capabilities → gated events withheld (fail closed): an old Swift client
    # that would throw on an unknown event never receives one.
    assert companion_route._client_can_receive(ActionProposedEvent(), []) is False
    assert companion_route._client_can_receive(DesktopActionEvent(), []) is False
    assert companion_route._client_can_receive(NarrationEvent(), []) is False
    assert companion_route._client_can_receive(ActionResultEvent(), []) is False
    # With the capability advertised → emitted.
    assert (
        companion_route._client_can_receive(ActionProposedEvent(), ["actions_v1"])
        is True
    )


def test_non_gated_events_always_pass():
    # Existing v1 events are never gated, regardless of advertised capabilities.
    assert companion_route._client_can_receive(DoneEvent(message_id="m1"), []) is True
    assert (
        companion_route._client_can_receive(MemoryUpdatedEvent(block="profile"), [])
        is True
    )


def test_pending_action_table_registered():
    table = CompanionPendingAction.__table__
    assert table.name == "companion_pending_actions"
    cols = set(table.columns.keys())
    assert {
        "id", "user_id", "conversation_id", "kind", "tool_name",
        "action_manifest", "payload_hmac", "idempotency_key", "status",
        "expires_at", "device_target", "recipient_display", "decision",
        "receipt", "resolved_at", "created_at", "updated_at",
    } <= cols
    uniques = {
        tuple(sorted(c.name for c in con.columns))
        for con in table.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("idempotency_key",) in uniques
