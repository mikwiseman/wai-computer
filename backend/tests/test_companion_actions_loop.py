"""run_turn(enable_actions=True): the bounded function-tool loop — lazy group
attach, gated write proposal (defer), no-call answer (P3)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.companion import (
    ActionProposedEvent,
    CompanionError,
    DoneEvent,
    TokenEvent,
    run_turn,
)
from app.models.companion import Conversation
from app.models.companion_pending_action import CompanionPendingAction
from app.models.user import User


@dataclass
class _Usage:
    input_tokens: int = 5
    output_tokens: int = 3
    cached_tokens: int = 1


@dataclass
class _FakeResponse:
    output: list[dict[str, Any]] = field(default_factory=list)
    output_text: str = ""
    usage: _Usage = field(default_factory=_Usage)
    status: str = "completed"
    error: Any = None
    incomplete_details: Any = None
    id: str = "resp-1"


@dataclass
class _DeltaEvent:
    delta: str
    type: str = "response.output_text.delta"


@dataclass
class _CompletedEvent:
    response: _FakeResponse
    type: str = "response.completed"


@dataclass
class _ErrorEvent:
    message: str
    type: str = "response.error"

    @property
    def error(self) -> dict[str, str]:
        return {"message": self.message}


class _AsyncEventStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class FakeOpenAISeq:
    """Returns a different event list per create() call (multi-step loop)."""

    def __init__(self, steps: list[list[Any]]):
        self._steps = list(steps)
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs.get("stream") is True
        events = self._steps.pop(0) if self._steps else []
        return _AsyncEventStream(events)


def _fc(name: str, arguments: str, call_id: str) -> dict[str, Any]:
    return {"type": "function_call", "name": name, "arguments": arguments, "call_id": call_id}


@pytest_asyncio.fixture
async def user_conv(db_session):
    user = User(email=f"loop-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    return user.id, conv.id


async def _collect(it: AsyncIterator) -> list:
    return [e async for e in it]


async def test_actions_turn_with_no_tool_call_answers_like_chat(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAISeq(
        [[_DeltaEvent("Готово."), _CompletedEvent(_FakeResponse(output_text="Готово."))]]
    )
    events = await _collect(
        run_turn(db_session, uid, cid, "что нового?", openai_client=fake, enable_actions=True)
    )
    text = "".join(e.text for e in events if isinstance(e, TokenEvent))
    assert text == "Готово."
    assert isinstance(events[-1], DoneEvent)
    assert len(fake.calls) == 1
    tools = fake.calls[0]["tools"]
    assert any(t.get("type") == "mcp" for t in tools)  # reads still on MCP
    assert any(t.get("type") == "web_search" for t in tools)  # "find online" on by default
    assert any(t.get("name") == "request_tool_group" for t in tools)  # lazy-attach offered
    # No write tool is attached until requested.
    assert not any(t.get("name") == "send_message_telegram" for t in tools)


async def test_write_tool_call_proposes_and_defers(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAISeq([
        # step 1: model asks for the telegram group
        [
            _CompletedEvent(
                _FakeResponse(
                    output=[_fc("request_tool_group", '{"group": "telegram"}', "c1")],
                    id="r1",
                )
            )
        ],
        # step 2: model calls the (now attached) send tool
        [
            _CompletedEvent(
                _FakeResponse(
                    output=[_fc("send_message_telegram", '{"text": "late"}', "c2")],
                    id="r2",
                )
            )
        ],
    ])
    events = await _collect(
        run_turn(db_session, uid, cid, "tell me I'm late", openai_client=fake, enable_actions=True)
    )

    proposed = [e for e in events if isinstance(e, ActionProposedEvent)]
    assert len(proposed) == 1
    assert proposed[0].tool == "send_message_telegram"
    assert proposed[0].recipient == "you"
    assert "late" in proposed[0].preview
    assert proposed[0].action_id

    # The send tool was attached only after the group was requested.
    assert len(fake.calls) == 2
    assert any(t.get("name") == "send_message_telegram" for t in fake.calls[1]["tools"])

    # A pending action was registered (NOT executed) — defer for approval.
    rows = (
        await db_session.execute(
            select(CompanionPendingAction).where(CompanionPendingAction.user_id == uid)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].tool_name == "send_message_telegram"
    assert rows[0].action_manifest["args"] == {"text": "late"}

    assert any(isinstance(e, DoneEvent) for e in events)


async def test_loop_surfaces_stream_error(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAISeq([[_ErrorEvent("boom in stream")]])
    with pytest.raises(CompanionError) as exc:
        await _collect(
            run_turn(db_session, uid, cid, "x", openai_client=fake, enable_actions=True)
        )
    assert exc.value.code == "stream_error"


async def test_loop_non_mutating_unavailable_tool_then_answers(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAISeq([
        # a read-classified function tool the loop doesn't serve → "unavailable"
        [_CompletedEvent(_FakeResponse(output=[_fc("list_recordings", "{}", "c1")], id="r1"))],
        [_DeltaEvent("ok"), _CompletedEvent(_FakeResponse(output_text="ok"))],
    ])
    events = await _collect(
        run_turn(db_session, uid, cid, "x", openai_client=fake, enable_actions=True)
    )
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "ok"
    assert any(isinstance(e, DoneEvent) for e in events)
    assert len(fake.calls) == 2
    # the tool result was fed back via previous_response_id
    assert fake.calls[1].get("previous_response_id") == "r1"
    # no pending action was created (it was not a mutating call)
    rows = (
        await db_session.execute(
            select(CompanionPendingAction).where(CompanionPendingAction.user_id == uid)
        )
    ).scalars().all()
    assert rows == []


async def test_loop_empty_output_raises(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAISeq([[_CompletedEvent(_FakeResponse(output_text="", output=[]))]])
    with pytest.raises(CompanionError) as exc:
        await _collect(
            run_turn(db_session, uid, cid, "x", openai_client=fake, enable_actions=True)
        )
    assert exc.value.code == "empty_model_output"


async def test_desktop_tool_proposes_desktop_action(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAISeq([
        [
            _CompletedEvent(
                _FakeResponse(
                    output=[_fc("request_tool_group", '{"group": "desktop"}', "c1")],
                    id="r1",
                )
            )
        ],
        [
            _CompletedEvent(
                _FakeResponse(
                    output=[_fc("desktop_open", '{"target": "mailto:a@x.com"}', "c2")],
                    id="r2",
                )
            )
        ],
    ])
    events = await _collect(
        run_turn(db_session, uid, cid, "open my email", openai_client=fake, enable_actions=True)
    )
    proposed = [e for e in events if isinstance(e, ActionProposedEvent)]
    assert len(proposed) == 1
    assert proposed[0].tool == "desktop_open"
    assert proposed[0].kind == "desktop_action"  # routed to the Mac edge, not a send
    assert "Open on your Mac" in proposed[0].preview
    assert any(t.get("name") == "desktop_open" for t in fake.calls[1]["tools"])

    rows = (
        await db_session.execute(
            select(CompanionPendingAction).where(CompanionPendingAction.user_id == uid)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "desktop_action"
    assert rows[0].tool_name == "desktop_open"
