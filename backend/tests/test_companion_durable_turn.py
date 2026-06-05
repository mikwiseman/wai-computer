"""Durable turns.

The assistant message is persisted from turn start (status='streaming'), so a
dropped stream is recoverable instead of lost; it finalizes to 'complete' or, on
error, 'failed' — never a forever-'streaming' ghost; and in-flight/failed turns
never feed the next prompt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import companion as companion_module
from app.core.companion import (
    CompanionError,
    DoneEvent,
    TurnStartEvent,
    _begin_assistant_message,
    _checkpoint_assistant_text,
    _load_history,
    run_turn,
    sweep_stale_streaming_messages,
)
from app.models.companion import ChatMessage, Conversation
from app.models.user import User


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class _FakeResponse:
    output: list[dict[str, Any]] = field(default_factory=list)
    output_text: str = ""
    usage: _Usage = field(default_factory=_Usage)
    status: str = "completed"
    error: Any = None
    incomplete_details: Any = None


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


class _Stream:
    def __init__(self, events: list[Any]):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class FakeOpenAI:
    def __init__(self, events: list[Any]):
        self.events = events
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream(self.events)


def _completed(text: str = "Готово.") -> _CompletedEvent:
    return _CompletedEvent(
        _FakeResponse(
            output_text=text,
            usage=_Usage(input_tokens=11, output_tokens=7, cached_tokens=3),
        )
    )


async def _collect(it: AsyncIterator) -> list[Any]:
    return [e async for e in it]


@pytest_asyncio.fixture
async def user_and_chat(db_session):
    user = User(email=f"u-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    return user, conv


async def test_assistant_message_persisted_and_finalized_complete(
    db_session, user_and_chat
):
    user, conv = user_and_chat
    fake = FakeOpenAI([_DeltaEvent("Нашёл."), _completed("Нашёл.")])

    events = await _collect(
        run_turn(db_session, user.id, conv.id, "вопрос", openai_client=fake)
    )

    turn_start, done = events[0], events[-1]
    assert isinstance(turn_start, TurnStartEvent)
    assert isinstance(done, DoneEvent)
    # The assistant id is stable from turn_start through to done.
    assert turn_start.assistant_message_id
    assert turn_start.assistant_message_id == done.message_id

    rows = (
        await db_session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    assistants = [m for m in rows if m.role == "assistant"]
    # Exactly one assistant row — the pre-created one was finalized, not duplicated.
    assert len(assistants) == 1
    assistant = assistants[0]
    assert str(assistant.id) == turn_start.assistant_message_id
    assert assistant.status == "complete"
    assert "Нашёл." in str(assistant.content)
    assert assistant.input_tokens == 11


async def test_turn_start_carries_title_on_first_turn(db_session, user_and_chat):
    user, conv = user_and_chat
    fake = FakeOpenAI([_DeltaEvent("ok"), _completed("ok")])
    events = await _collect(
        run_turn(db_session, user.id, conv.id, "Plan my week", openai_client=fake)
    )
    assert events[0].title == "Plan my week"


async def test_stream_error_marks_assistant_failed(db_session, user_and_chat):
    user, conv = user_and_chat
    fake = FakeOpenAI([_ErrorEvent("upstream down")])

    with pytest.raises(CompanionError):
        await _collect(
            run_turn(db_session, user.id, conv.id, "hi", openai_client=fake)
        )

    rows = (
        await db_session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conv.id,
                ChatMessage.role == "assistant",
            )
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    # The streaming row exists and is flipped to 'failed' (no silent loss, no ghost).
    assert len(rows) == 1
    assert rows[0].status == "failed"


async def test_streaming_and_failed_rows_excluded_from_history(
    db_session, user_and_chat
):
    user, conv = user_and_chat
    db_session.add(
        ChatMessage(conversation_id=conv.id, role="user", content="q", status="complete")
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=[{"type": "text", "text": "done"}],
            status="complete",
        )
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=[{"type": "text", "text": "partial"}],
            status="streaming",
        )
    )
    db_session.add(
        ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content=[{"type": "text", "text": "broke"}],
            status="failed",
        )
    )
    await db_session.flush()

    history = await _load_history(db_session, conv.id)
    texts = [str(m.content) for m in history]
    assert any("done" in t for t in texts)
    assert not any("partial" in t for t in texts)
    assert not any("broke" in t for t in texts)


async def test_checkpoint_persists_partial_text(db_session, user_and_chat):
    _, conv = user_and_chat
    msg = await _begin_assistant_message(db_session, conv.id, "gpt-5.5")
    assert msg.status == "streaming"

    await _checkpoint_assistant_text(db_session, msg.id, "half an answer")

    refreshed = await db_session.get(ChatMessage, msg.id, populate_existing=True)
    assert "half an answer" in str(refreshed.content)
    assert refreshed.status == "streaming"  # still in flight


async def test_plain_path_checkpoints_when_threshold_low(
    db_session, user_and_chat, monkeypatch
):
    user, conv = user_and_chat
    monkeypatch.setattr(companion_module, "CHECKPOINT_EVERY_N_DELTAS", 1)
    fake = FakeOpenAI([_DeltaEvent("aa"), _DeltaEvent("bb"), _completed("aabb")])

    events = await _collect(
        run_turn(db_session, user.id, conv.id, "hi", openai_client=fake)
    )
    assert isinstance(events[-1], DoneEvent)

    row = (
        await db_session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conv.id,
                ChatMessage.role == "assistant",
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert "aabb" in str(row.content)
    assert row.status == "complete"


async def test_sweep_marks_old_streaming_rows_failed(db_session, user_and_chat):
    _, conv = user_and_chat
    fresh = await _begin_assistant_message(db_session, conv.id, "gpt-5.5")
    stale = await _begin_assistant_message(db_session, conv.id, "gpt-5.5")
    stale.created_at = datetime.now(timezone.utc) - timedelta(seconds=999)
    await db_session.flush()

    swept = await sweep_stale_streaming_messages(db_session, older_than_seconds=120)

    assert swept == 1
    stale_row = await db_session.get(ChatMessage, stale.id, populate_existing=True)
    fresh_row = await db_session.get(ChatMessage, fresh.id, populate_existing=True)
    assert stale_row.status == "failed"
    assert fresh_row.status == "streaming"
