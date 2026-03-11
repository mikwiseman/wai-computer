"""Tests for the core chat pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import chat as chat_core
from app.models.chat import ChatMessage, ChatSession
from app.models.recording import Recording, Segment
from app.models.user import User


def _vector(index: int) -> list[float]:
    values = [0.0] * 384
    values[index] = 1.0
    return values


async def _create_user(db_session: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="hashed")
    db_session.add(user)
    await db_session.flush()
    return user


async def _create_recording(
    db_session: AsyncSession,
    user_id: UUID,
    *,
    title: str,
) -> Recording:
    recording = Recording(user_id=user_id, title=title, type="note", language="en")
    db_session.add(recording)
    await db_session.flush()
    return recording


class FakeAPIConnectionError(Exception):
    pass


class FakeRateLimitError(Exception):
    pass


class FakeAPIStatusError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class FakeMessagesAPI:
    def __init__(self, response_or_error: object, calls: list[dict] | None = None):
        self._response_or_error = response_or_error
        self._calls = calls

    async def create(self, **kwargs):
        if self._calls is not None:
            self._calls.append(kwargs)

        if isinstance(self._response_or_error, Exception):
            raise self._response_or_error

        return self._response_or_error


class FakeAsyncAnthropic:
    response_or_error: object = SimpleNamespace(
        content=[SimpleNamespace(text="Default answer")]
    )
    calls: list[dict] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.messages = FakeMessagesAPI(self.response_or_error, self.calls)


def _fake_anthropic_module() -> SimpleNamespace:
    return SimpleNamespace(
        AsyncAnthropic=FakeAsyncAnthropic,
        APIConnectionError=FakeAPIConnectionError,
        RateLimitError=FakeRateLimitError,
        APIStatusError=FakeAPIStatusError,
    )


@pytest.mark.asyncio
async def test_retrieve_context_filters_by_user_and_recording_ids(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    owner = await _create_user(db_session, "chat.context.owner@example.com")
    other = await _create_user(db_session, "chat.context.other@example.com")

    included = await _create_recording(db_session, owner.id, title="Included Recording")
    excluded = await _create_recording(db_session, owner.id, title="Excluded Recording")
    other_recording = await _create_recording(db_session, other.id, title="Other Recording")

    db_session.add_all(
        [
            Segment(
                recording_id=included.id,
                speaker="Speaker 1",
                content="Roadmap launch details",
                start_ms=0,
                end_ms=900,
                confidence=0.95,
                embedding=_vector(0),
            ),
            Segment(
                recording_id=excluded.id,
                speaker="Speaker 2",
                content="Budget review details",
                start_ms=1000,
                end_ms=1900,
                confidence=0.9,
                embedding=_vector(1),
            ),
            Segment(
                recording_id=other_recording.id,
                speaker="Speaker 3",
                content="Other user's roadmap notes",
                start_ms=2000,
                end_ms=2900,
                confidence=0.9,
                embedding=_vector(0),
            ),
        ]
    )
    await db_session.flush()

    async def fake_generate_embedding(_: str) -> list[float]:
        return _vector(0)

    monkeypatch.setattr(chat_core, "generate_embedding", fake_generate_embedding)

    filtered_rows = await chat_core.retrieve_context(
        db_session,
        owner.id,
        "roadmap",
        recording_ids=[included.id],
    )
    assert len(filtered_rows) == 1
    assert filtered_rows[0].recording_title == "Included Recording"
    assert filtered_rows[0].content == "Roadmap launch details"

    all_rows = await chat_core.retrieve_context(db_session, owner.id, "roadmap")
    assert {str(row.recording_id) for row in all_rows} == {
        str(included.id),
        str(excluded.id),
    }


def test_build_context_text_handles_empty_and_formats_segments():
    assert chat_core.build_context_text([]) == "No relevant transcript segments found."

    rows = [
        SimpleNamespace(
            recording_title="Weekly Sync",
            speaker="Alice",
            content="The launch is on Tuesday.",
        ),
        SimpleNamespace(
            recording_title=None,
            speaker=None,
            content="No owner on this segment.",
        ),
    ]

    text = chat_core.build_context_text(rows)
    assert "[Recording: Weekly Sync] [Alice]: The launch is on Tuesday." in text
    assert "[Recording: Untitled] [Unknown]: No owner on this segment." in text


@pytest.mark.asyncio
async def test_chat_with_recordings_creates_session_messages_and_title(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await _create_user(db_session, "chat.success@example.com")
    context_rows = [
        SimpleNamespace(
            id=uuid4(),
            recording_id=uuid4(),
            recording_title="Launch Plan",
            speaker="Alice",
            content="The launch is on Tuesday.",
            start_ms=0,
            end_ms=1200,
        ),
        SimpleNamespace(
            id=uuid4(),
            recording_id=uuid4(),
            recording_title="Launch Plan",
            speaker="Bob",
            content="Alice will handle the demo.",
            start_ms=1300,
            end_ms=2400,
        ),
    ]
    anthropic_calls: list[dict] = []

    async def fake_retrieve_context(*args, **kwargs):
        return context_rows

    monkeypatch.setattr(chat_core, "retrieve_context", fake_retrieve_context)
    monkeypatch.setattr(chat_core, "anthropic", _fake_anthropic_module())
    monkeypatch.setattr(chat_core, "_anthropic_client", None)
    monkeypatch.setattr(chat_core.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        FakeAsyncAnthropic,
        "response_or_error",
        SimpleNamespace(content=[SimpleNamespace(text="Final answer")]),
    )
    monkeypatch.setattr(FakeAsyncAnthropic, "calls", anthropic_calls)

    result = await chat_core.chat_with_recordings(
        db=db_session,
        user_id=user.id,
        question="What happened in the meeting?",
    )

    assert result.answer == "Final answer"
    assert len(result.source_segments) == 2
    assert anthropic_calls[0]["messages"][-1]["content"].startswith(
        "Context from meeting transcripts:"
    )

    session = await db_session.get(ChatSession, UUID(result.session_id))
    assert session is not None
    assert session.title == "What happened in the meeting?"

    stored_messages = (
        await db_session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    assert [message.role for message in stored_messages] == ["user", "assistant"]
    assert stored_messages[0].content == "What happened in the meeting?"
    assert stored_messages[1].content == "Final answer"
    assert stored_messages[1].source_segment_ids == [str(row.id) for row in context_rows]


@pytest.mark.asyncio
async def test_chat_with_recordings_reuses_existing_session_and_history(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await _create_user(db_session, "chat.history@example.com")
    session = ChatSession(user_id=user.id, title="Existing title", recording_ids=[str(uuid4())])
    db_session.add(session)
    await db_session.flush()

    db_session.add_all(
        [
            ChatMessage(
                session_id=session.id,
                role="user",
                content="What is the plan?",
            ),
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content="The plan is to launch next week.",
            ),
        ]
    )
    await db_session.flush()

    anthropic_calls: list[dict] = []

    async def fake_retrieve_context(*args, **kwargs):
        return []

    monkeypatch.setattr(chat_core, "retrieve_context", fake_retrieve_context)
    monkeypatch.setattr(chat_core, "anthropic", _fake_anthropic_module())
    monkeypatch.setattr(chat_core, "_anthropic_client", None)
    monkeypatch.setattr(chat_core.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(
        FakeAsyncAnthropic,
        "response_or_error",
        SimpleNamespace(content=[SimpleNamespace(text="Follow-up answer")]),
    )
    monkeypatch.setattr(FakeAsyncAnthropic, "calls", anthropic_calls)

    result = await chat_core.chat_with_recordings(
        db=db_session,
        user_id=user.id,
        question="Who owns the next step?",
        session_id=session.id,
    )

    assert result.answer == "Follow-up answer"
    history_pairs = {
        (message["role"], message["content"])
        for message in anthropic_calls[0]["messages"][:-1]
    }
    assert history_pairs == {
        ("user", "What is the plan?"),
        ("assistant", "The plan is to launch next week."),
    }
    assert "No relevant transcript segments found." in anthropic_calls[0]["messages"][-1]["content"]

    refreshed_session = await db_session.get(ChatSession, session.id)
    assert refreshed_session is not None
    assert refreshed_session.title == "Existing title"

    stored_messages = (
        await db_session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    assert len(stored_messages) == 4
    assert stored_messages[-1].content == "Follow-up answer"


@pytest.mark.asyncio
async def test_chat_with_recordings_requires_configured_anthropic_key(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await _create_user(db_session, "chat.no-key@example.com")
    monkeypatch.setattr(chat_core.settings, "anthropic_api_key", "")

    with pytest.raises(HTTPException) as exc_info:
        await chat_core.chat_with_recordings(
            db=db_session,
            user_id=user.id,
            question="Hello?",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Chat service not configured"


@pytest.mark.asyncio
async def test_chat_with_recordings_rejects_missing_session(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user = await _create_user(db_session, "chat.missing-session@example.com")
    monkeypatch.setattr(chat_core.settings, "anthropic_api_key", "test-key")

    with pytest.raises(HTTPException) as exc_info:
        await chat_core.chat_with_recordings(
            db=db_session,
            user_id=user.id,
            question="Hello?",
            session_id=uuid4(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Chat session not found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_or_error", "expected_status", "expected_detail"),
    [
        (SimpleNamespace(content=[]), 502, "Empty response from AI service"),
        (FakeAPIConnectionError(), 502, "Unable to connect to AI service"),
        (
            FakeRateLimitError(),
            429,
            "AI service rate limit exceeded. Please try again later.",
        ),
        (FakeAPIStatusError("upstream failed"), 502, "AI service error: upstream failed"),
    ],
)
async def test_chat_with_recordings_maps_upstream_failures(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    response_or_error: object,
    expected_status: int,
    expected_detail: str,
):
    user = await _create_user(db_session, f"chat.fail.{uuid4()}@example.com")

    async def fake_retrieve_context(*args, **kwargs):
        return []

    monkeypatch.setattr(chat_core, "retrieve_context", fake_retrieve_context)
    monkeypatch.setattr(chat_core, "anthropic", _fake_anthropic_module())
    monkeypatch.setattr(chat_core, "_anthropic_client", None)
    monkeypatch.setattr(chat_core.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(FakeAsyncAnthropic, "response_or_error", response_or_error)
    monkeypatch.setattr(FakeAsyncAnthropic, "calls", [])

    with pytest.raises(HTTPException) as exc_info:
        await chat_core.chat_with_recordings(
            db=db_session,
            user_id=user.id,
            question="What happened?",
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
