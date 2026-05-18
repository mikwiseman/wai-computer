"""Tests for the Companion tool loop + structured synthesis + SSE wire."""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core import companion as companion_module
from app.core.companion import (
    TOOL_CALL_CAP,
    CitationEvent,
    DoneEvent,
    TokenEvent,
    ToolCallEvent,
    TurnContext,
    run_turn,
    system_prompt_for,
)
from app.models.companion import ChatMessage, Conversation, MessageCitation

# ------------- Fake OpenAI client -------------


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
    """Mimics `response.output_text.delta` SSE event from Responses streaming."""

    delta: str
    type: str = "response.output_text.delta"


@dataclass
class _CompletedEvent:
    """Mimics `response.completed` event with a usage-bearing response."""

    response: _FakeResponse
    type: str = "response.completed"


class _AsyncEventStream:
    """Async iterator over a pre-built list of streaming events."""

    def __init__(self, events: list[Any]):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class FakeOpenAI:
    """Replays a scripted list of Responses-API responses, in order.

    Each scripted entry is either:
    - a `_FakeResponse` (non-streaming Phase A turn, or a Phase B response
      that is auto-chunked into delta events when stream=True);
    - a list of streaming events (consumed verbatim when stream=True).
    """

    def __init__(self, *scripted: Any):
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._scripted:
            raise AssertionError("FakeOpenAI ran out of scripted responses")
        nxt = self._scripted.pop(0)
        if kwargs.get("stream"):
            if isinstance(nxt, list):
                return _AsyncEventStream(nxt)
            return _AsyncEventStream(_response_to_streaming_events(nxt))
        return nxt


def _response_to_streaming_events(resp: _FakeResponse) -> list[Any]:
    """Convert a buffered Phase-B response into delta + completed events."""
    text = resp.output_text or _join_output_text(resp.output)
    chunk_size = max(1, len(text) // 8) if text else 1
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [text]
    events: list[Any] = [_DeltaEvent(delta=chunk) for chunk in chunks]
    events.append(_CompletedEvent(response=resp))
    return events


def _join_output_text(items: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for item in items:
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                out.append(c.get("text", ""))
    return "".join(out)


def _tool_call_response(call_id: str, name: str, args: dict[str, Any]) -> _FakeResponse:
    return _FakeResponse(
        output=[
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(args),
            }
        ]
    )


def _text_response(text: str) -> _FakeResponse:
    return _FakeResponse(
        output=[
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        output_text=text,
    )


def _structured_response(markdown: str, citations: list[dict[str, Any]]) -> _FakeResponse:
    payload = json.dumps({"markdown": markdown, "citations": citations})
    return _FakeResponse(
        output=[
            {
                "type": "message",
                "content": [{"type": "output_text", "text": payload}],
            }
        ],
        output_text=payload,
    )


# ------------- Fixtures -------------


@pytest_asyncio.fixture
async def setup_user_and_recording(db_session):
    """Seed a user + recording + 2 segments so search_transcripts returns rows."""
    from app.models.recording import Recording, Segment
    from app.models.user import User

    user = User(email=f"u-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    recording = Recording(
        user_id=user.id,
        title="Standup",
        type="meeting",
        status="ready",
    )
    db_session.add(recording)
    await db_session.flush()

    seg1 = Segment(
        recording_id=recording.id,
        speaker="Anna",
        content="ship the auth refactor by Friday",
        start_ms=1000,
        end_ms=4000,
        embedding=[0.0] * 1536,
    )
    seg2 = Segment(
        recording_id=recording.id,
        speaker="Mik",
        content="block off Tuesday for the migration",
        start_ms=5000,
        end_ms=8000,
        embedding=[0.0] * 1536,
    )
    db_session.add_all([seg1, seg2])
    await db_session.flush()

    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()

    return {
        "user": user,
        "recording": recording,
        "segments": [seg1, seg2],
        "conversation": conv,
    }


@pytest.fixture
def fake_embedding(monkeypatch):
    """Avoid hitting OpenAI's embedding endpoint inside retrieve_context."""

    async def fake_generate(text: str) -> list[float]:
        return [0.0] * 1536

    monkeypatch.setattr(
        "app.core.qa.generate_embedding", fake_generate, raising=True
    )


async def _collect(it: AsyncIterator):
    return [e async for e in it]


# ------------- Tests for run_turn (service-level) -------------


class TestRunTurn:
    async def test_happy_path_one_search_then_answer(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        s = setup_user_and_recording
        seg_id = str(s["segments"][0].id)

        fake = FakeOpenAI(
            _tool_call_response(
                "c1",
                "search_transcripts",
                {"query": "what did Anna commit to?"},
            ),
            _text_response("done searching"),
            _structured_response(
                markdown="Anna agreed to ship the auth refactor by Friday [1].",
                citations=[
                    {"index": 1, "segment_id": seg_id, "span_start": 0, "span_end": 50}
                ],
            ),
        )

        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "What did Anna commit to?",
                openai_client=fake,
            )
        )

        event_types = [type(e).__name__ for e in events]
        assert event_types[0] == "TurnStartEvent"
        assert "ToolCallEvent" in event_types
        assert "ToolResultEvent" in event_types
        assert "TokenEvent" in event_types
        assert "CitationEvent" in event_types
        assert event_types[-1] == "DoneEvent"

        # Citation in the stream matches the seeded segment
        citations = [e for e in events if isinstance(e, CitationEvent)]
        assert len(citations) == 1
        assert citations[0].segment_id == seg_id

        # Persisted: user msg + assistant msg + 1 citation row
        from sqlalchemy import select as _select
        msgs = (
            (
                await db_session.execute(
                    _select(ChatMessage).where(
                        ChatMessage.conversation_id == s["conversation"].id
                    )
                )
            )
            .scalars()
            .all()
        )
        roles = sorted([m.role for m in msgs])
        assert roles == ["assistant", "user"]
        assistant_msg = next(m for m in msgs if m.role == "assistant")
        assert assistant_msg.model == "gpt-5.5"
        cits = (
            (
                await db_session.execute(
                    _select(MessageCitation).where(
                        MessageCitation.message_id == assistant_msg.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(cits) == 1
        assert str(cits[0].segment_id) == seg_id

    async def test_hallucinated_citation_is_dropped_no_retry(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        s = setup_user_and_recording
        valid_seg_id = str(s["segments"][0].id)
        bogus_seg_id = str(uuid4())  # not in any search result

        fake = FakeOpenAI(
            _tool_call_response("c1", "search_transcripts", {"query": "x"}),
            _text_response("done"),
            _structured_response(
                markdown="A [1] B [2].",
                citations=[
                    {
                        "index": 1,
                        "segment_id": valid_seg_id,
                        "span_start": 0,
                        "span_end": 1,
                    },
                    {
                        "index": 2,
                        "segment_id": bogus_seg_id,
                        "span_start": 2,
                        "span_end": 3,
                    },
                ],
            ),
        )

        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "test",
                openai_client=fake,
            )
        )

        citations = [e for e in events if isinstance(e, CitationEvent)]
        assert len(citations) == 1
        assert citations[0].segment_id == valid_seg_id

        # Only 3 OpenAI calls total — no retry after citation drop
        assert len(fake.calls) == 3

    async def test_tool_call_cap_enforced(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        s = setup_user_and_recording

        # Phase A consumes exactly TOOL_CALL_CAP scripted tool-call responses;
        # Phase B consumes the trailing structured response. With this exact
        # 7-item script, the loop transitions cleanly only if the cap stops it
        # at TOOL_CALL_CAP — one extra Phase A iteration would steal Phase B's
        # response and break JSON parsing.
        scripted = [
            _tool_call_response(f"c{i}", "search_transcripts", {"query": f"q{i}"})
            for i in range(TOOL_CALL_CAP)
        ]
        scripted.append(_structured_response("done.", []))
        fake = FakeOpenAI(*scripted)

        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "test",
                openai_client=fake,
            )
        )

        tool_calls_emitted = [e for e in events if isinstance(e, ToolCallEvent)]
        assert len(tool_calls_emitted) == TOOL_CALL_CAP
        assert len(fake.calls) == TOOL_CALL_CAP + 1
        assert any(isinstance(e, DoneEvent) for e in events)

    async def test_no_tool_calls_goes_straight_to_synthesis(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        s = setup_user_and_recording

        fake = FakeOpenAI(
            _text_response("nothing to look up"),
            _structured_response("Nothing in your recordings touches that.", []),
        )

        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "What's the airspeed velocity of an unladen swallow?",
                openai_client=fake,
            )
        )

        # First event is the turn_start, last is done; in between the model's
        # markdown is streamed as one or more TokenEvents (chunking varies).
        assert isinstance(events[0], companion_module.TurnStartEvent)
        assert isinstance(events[-1], DoneEvent)
        token_texts = [e.text for e in events if isinstance(e, TokenEvent)]
        assert "".join(token_texts) == "Nothing in your recordings touches that."

    async def test_other_user_cannot_post_to_chat(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        s = setup_user_and_recording
        from fastapi import HTTPException

        other_user_id = uuid4()
        fake = FakeOpenAI()  # never reached

        with pytest.raises(HTTPException) as exc_info:
            await _collect(
                run_turn(
                    db_session,
                    other_user_id,
                    s["conversation"].id,
                    "intrude",
                    openai_client=fake,
                )
            )
        assert exc_info.value.status_code == 404

    async def test_history_window_truncates(
        self, db_session, setup_user_and_recording, fake_embedding, monkeypatch
    ):
        """With HISTORY_WINDOW=20, older messages are not sent to the model."""
        s = setup_user_and_recording

        # Pre-seed 25 user messages so the new turn would otherwise see 26.
        for i in range(25):
            db_session.add(
                ChatMessage(
                    conversation_id=s["conversation"].id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"old msg {i}",
                )
            )
        await db_session.flush()

        fake = FakeOpenAI(
            _text_response("ok"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "new turn",
                openai_client=fake,
            )
        )

        # First create() call received at most HISTORY_WINDOW prior messages.
        first_input = fake.calls[0]["input"]
        # Exclude the freshly persisted user message (it's at the tail).
        assert len(first_input) <= companion_module.HISTORY_WINDOW + 1


    async def test_session_developer_message_injected_when_context_given(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """The per-turn context (date / tz / scope / viewing) goes into the
        input as a developer message — NOT into instructions — so the
        cacheable prefix stays stable across turns."""
        s = setup_user_and_recording
        fake = FakeOpenAI(
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "hello",
                turn_context=TurnContext(
                    client_local_date="2026-05-18",
                    client_timezone="Europe/Reykjavik",
                ),
                openai_client=fake,
            )
        )

        first_input = fake.calls[0]["input"]
        # Developer message is the first entry; history follows.
        assert first_input[0]["role"] == "developer"
        content = first_input[0]["content"]
        assert "2026-05-18" in content
        assert "Europe/Reykjavik" in content
        assert "<session>" in content and "</session>" in content
        # Instructions stay free of per-turn variability so cache holds.
        assert "2026-05-18" not in fake.calls[0]["instructions"]
        assert "Europe/Reykjavik" not in fake.calls[0]["instructions"]

    async def test_session_message_flags_missing_client_fields(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """No fallbacks: when the client did not send tz / date, the model
        is told so explicitly instead of getting a silent UTC default."""
        s = setup_user_and_recording
        fake = FakeOpenAI(
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "hi",
                turn_context=TurnContext(),
                openai_client=fake,
            )
        )
        content = fake.calls[0]["input"][0]["content"]
        assert "date: unknown" in content
        assert "timezone: unknown" in content

    async def test_yesterday_query_carries_local_date_to_list_recordings(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """End-to-end the date context reaches the model: when it asks
        list_recordings with date_from/date_to it does so against the
        date the client supplied, not a server-side guess."""
        s = setup_user_and_recording
        fake = FakeOpenAI(
            _tool_call_response(
                "c1",
                "list_recordings",
                {
                    "date_from": "2026-05-17T00:00:00+00:00",
                    "date_to": "2026-05-17T23:59:59+00:00",
                    "limit": 10,
                },
            ),
            _text_response("done"),
            _structured_response("nothing on that day.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "О чем говорили вчера",
                turn_context=TurnContext(
                    client_local_date="2026-05-18",
                    client_timezone="Europe/Reykjavik",
                ),
                openai_client=fake,
            )
        )
        # First Phase-A call must carry the developer session message with
        # the user's local date so the model has an anchor for "вчера".
        first_input = fake.calls[0]["input"]
        assert first_input[0]["role"] == "developer"
        assert "2026-05-18" in first_input[0]["content"]
        # And the list_recordings tool call landed (consumed by FakeOpenAI).
        tool_calls = [e for e in fake.calls if "tools" in e]
        assert tool_calls  # at least the Phase-A call had tools

    async def test_system_prompt_renders_user_profile_and_format_rules(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """The cacheable prefix contains identity + user_profile + tool
        guidance + answer-format rules. With the existing User defaults
        this gives the model what it needs to answer in Russian to a
        Russian-default user without per-turn nudging."""
        s = setup_user_and_recording
        user_row = s["user"]
        prompt = system_prompt_for(user_row)
        assert "<identity>" in prompt
        assert "<user_profile>" in prompt
        assert f"default_language: {user_row.default_language}" in prompt
        assert "<tool_guidance>" in prompt
        assert "list_recordings" in prompt
        assert "<answer_format>" in prompt
        assert "Match the language" in prompt
        # The <memory> SECTION (not the word "<memory>" in tool guidance)
        # only appears once user_memory blocks render content.
        assert "<memory>\n##" not in prompt

    async def test_list_recordings_returns_summary_topics_folder(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """Granola-style enrichment: list_recordings carries enough metadata
        for the model to pick the right recording without a second call."""
        from app.models.recording import Folder, Summary

        s = setup_user_and_recording
        folder = Folder(user_id=s["user"].id, name="MFC")
        db_session.add(folder)
        await db_session.flush()
        s["recording"].folder_id = folder.id
        summary = Summary(
            recording_id=s["recording"].id,
            summary="Sprint planning for v1.0. Decided to gate launch on Phase 13.",
            topics=["v1.0", "release"],
        )
        db_session.add(summary)
        await db_session.flush()

        # Drive the model: just have it call list_recordings, no other tools.
        fake = FakeOpenAI(
            _tool_call_response("c1", "list_recordings", {}),
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "What recordings do I have?",
                openai_client=fake,
            )
        )

        # Inspect what the model received as the function_call_output for c1.
        # That is appended to the input of subsequent calls.
        second_input = fake.calls[1]["input"]
        outputs = [
            json.loads(item["output"])
            for item in second_input
            if item.get("type") == "function_call_output"
        ]
        assert outputs, "no function_call_output was passed back to model"
        recordings = outputs[0]["recordings"]
        assert len(recordings) == 1
        r = recordings[0]
        assert r["title"] == "Standup"
        assert r["folder"] == "MFC"
        assert r["type"] == "meeting"
        assert r["topics"] == ["v1.0", "release"]
        assert r["summary_one_line"].startswith("Sprint planning")

    async def test_get_action_items_default_filters_to_pending(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        from app.models.recording import ActionItem

        s = setup_user_and_recording
        item_open = ActionItem(
            recording_id=s["recording"].id,
            task="ship the auth refactor",
            owner="Anna",
            priority="high",
            status="pending",
        )
        item_done = ActionItem(
            recording_id=s["recording"].id,
            task="old work",
            status="completed",
        )
        db_session.add_all([item_open, item_done])
        await db_session.flush()

        fake = FakeOpenAI(
            _tool_call_response("c1", "get_action_items", {}),
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "что я должен",
                openai_client=fake,
            )
        )

        outputs = [
            json.loads(item["output"])
            for item in fake.calls[1]["input"]
            if item.get("type") == "function_call_output"
        ]
        items = outputs[0]["action_items"]
        assert len(items) == 1
        assert items[0]["task"] == "ship the auth refactor"
        assert items[0]["status"] == "pending"
        assert items[0]["recording_title"] == "Standup"

    async def test_get_highlights_filters_by_min_importance(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        from app.models.highlight import Highlight

        s = setup_user_and_recording
        db_session.add_all(
            [
                Highlight(
                    recording_id=s["recording"].id,
                    category="decision",
                    title="Block Tuesday",
                    importance="high",
                ),
                Highlight(
                    recording_id=s["recording"].id,
                    category="aside",
                    title="Coffee was good",
                    importance="low",
                ),
            ]
        )
        await db_session.flush()

        fake = FakeOpenAI(
            _tool_call_response(
                "c1", "get_highlights", {"min_importance": "high"}
            ),
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "что важного на этой неделе",
                openai_client=fake,
            )
        )
        outputs = [
            json.loads(item["output"])
            for item in fake.calls[1]["input"]
            if item.get("type") == "function_call_output"
        ]
        highlights = outputs[0]["highlights"]
        assert len(highlights) == 1
        assert highlights[0]["importance"] == "high"

    async def test_search_people_finds_via_entity_relations(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        from app.models.entity import Entity, EntityRelation

        s = setup_user_and_recording
        alice = Entity(
            user_id=s["user"].id,
            type="person",
            name="Alice Chen",
        )
        bob = Entity(
            user_id=s["user"].id,
            type="person",
            name="Bob",
        )
        db_session.add_all([alice, bob])
        await db_session.flush()
        db_session.add(
            EntityRelation(
                source_id=alice.id,
                target_id=bob.id,
                relation_type="mentioned_in",
                recording_id=s["recording"].id,
            )
        )
        await db_session.flush()

        fake = FakeOpenAI(
            _tool_call_response("c1", "search_people", {"name": "Alice"}),
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "what did Alice say?",
                openai_client=fake,
            )
        )

        outputs = [
            json.loads(item["output"])
            for item in fake.calls[1]["input"]
            if item.get("type") == "function_call_output"
        ]
        recordings = outputs[0]["recordings"]
        assert len(recordings) == 1
        assert recordings[0]["title"] == "Standup"

    async def test_search_people_returns_empty_when_no_match(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        fake = FakeOpenAI(
            _tool_call_response("c1", "search_people", {"name": "Nobody"}),
            _text_response("done"),
            _structured_response("ok.", []),
        )
        s = setup_user_and_recording
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "kid foo",
                openai_client=fake,
            )
        )
        outputs = [
            json.loads(item["output"])
            for item in fake.calls[1]["input"]
            if item.get("type") == "function_call_output"
        ]
        assert outputs[0]["recordings"] == []

    async def test_new_tools_are_advertised_to_model(self, fake_embedding):
        from app.core.companion import tool_definitions

        names = {t["name"] for t in tool_definitions()}
        assert {
            "search_transcripts",
            "get_recording_summary",
            "list_recordings",
            "get_action_items",
            "get_highlights",
            "search_people",
            "remember",
        } <= names

    async def test_remember_tool_writes_to_memory_and_emits_event(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """Calling the `remember` tool writes to the user's memory block
        and surfaces a typed MemoryUpdatedEvent on the SSE stream."""
        from app.core.companion import MemoryUpdatedEvent
        from app.core.user_memory import get_or_seed_blocks

        s = setup_user_and_recording
        fake = FakeOpenAI(
            _tool_call_response(
                "c1",
                "remember",
                {
                    "block": "human",
                    "operation": "append",
                    "content": "Lives in Reykjavik",
                },
            ),
            _text_response("done"),
            _structured_response("Saved.", []),
        )
        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "запомни что я живу в Рейкьявике",
                openai_client=fake,
            )
        )
        # The typed memory-updated event is present in the stream.
        mems = [e for e in events if isinstance(e, MemoryUpdatedEvent)]
        assert len(mems) == 1
        assert mems[0].block == "human"
        assert mems[0].operation == "append"

        # And the underlying block was persisted.
        blocks = await get_or_seed_blocks(db_session, s["user"].id)
        assert "Reykjavik" in blocks["human"].body

    async def test_memory_blocks_render_into_instructions(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """Once a memory block has content, subsequent turns ship it in
        the cacheable `instructions` prefix so the model knows it."""
        from app.core.user_memory import write_block

        s = setup_user_and_recording
        await write_block(
            db_session,
            s["user"].id,
            "human",
            "append",
            "Lives in Reykjavik",
            source="system",
        )
        fake = FakeOpenAI(
            _text_response("done"),
            _structured_response("ok.", []),
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "where do I live?",
                openai_client=fake,
            )
        )
        instructions = fake.calls[0]["instructions"]
        assert "<memory>" in instructions
        assert "## human" in instructions
        assert "Reykjavik" in instructions

    async def test_instructions_stay_stable_across_turns_for_same_user(
        self, db_session, setup_user_and_recording, fake_embedding
    ):
        """Two back-to-back turns send byte-identical `instructions` so the
        OpenAI prompt cache can match the prefix."""
        s = setup_user_and_recording
        fake = FakeOpenAI(
            _text_response("done"),
            _structured_response("a.", []),
            _text_response("done"),
            _structured_response("b.", []),
        )
        ctx_a = TurnContext(
            client_local_date="2026-05-18", client_timezone="Europe/Reykjavik"
        )
        ctx_b = TurnContext(
            client_local_date="2026-05-19", client_timezone="Europe/Reykjavik"
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "first",
                turn_context=ctx_a,
                openai_client=fake,
            )
        )
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "second",
                turn_context=ctx_b,
                openai_client=fake,
            )
        )
        # Phase-A calls for turn 1 and turn 2:
        assert fake.calls[0]["instructions"] == fake.calls[2]["instructions"]


# ------------- Tests for the SSE route (HTTP wire) -------------


@pytest_asyncio.fixture
async def stub_openai_for_route(monkeypatch):
    """Install a route-level fake OpenAI that returns a one-turn happy path."""

    captured_segment_ids: list[str] = []

    def make_fake_for_user(seg_id: str):
        return FakeOpenAI(
            _tool_call_response("c1", "search_transcripts", {"query": "x"}),
            _text_response("done"),
            _structured_response(
                markdown="Found it [1].",
                citations=[
                    {
                        "index": 1,
                        "segment_id": seg_id,
                        "span_start": 0,
                        "span_end": 8,
                    }
                ],
            ),
        )

    # The route fetches via get_openai_client(); we'll set up a fresh fake per call.
    holder = {"fake": None}

    def installer(seg_id: str):
        fake = make_fake_for_user(seg_id)
        holder["fake"] = fake
        # Patch the imported name inside companion.py (where it's actually called).
        monkeypatch.setattr(
            "app.core.companion.get_openai_client",
            lambda: fake,
            raising=True,
        )

    yield installer, captured_segment_ids, holder


class TestPostMessageSSE:
    async def test_sse_event_protocol_end_to_end(
        self,
        client: AsyncClient,
        auth_headers: dict,
        stub_openai_for_route,
        monkeypatch,
    ):
        installer, _, holder = stub_openai_for_route

        # Seed a recording + segment + chat as the authed user via API + DB.
        # Easiest: call the API to make a chat, then manually inject a segment.
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        # Fetch the user id from the JWT (or just create the recording via DB).
        # Simpler: use the db_session override; we'll seed via the override.
        from app.db.session import get_db
        from app.main import app

        # The override yields a single shared session.
        deps = app.dependency_overrides[get_db]
        session = None
        async for s in deps():
            session = s
            break

        from sqlalchemy import select as _select

        from app.models.companion import Conversation as _Conv
        from app.models.recording import Recording, Segment

        conv = (
            await session.execute(_select(_Conv).where(_Conv.id == uuid.UUID(chat["id"])))
        ).scalar_one()
        recording = Recording(
            user_id=conv.user_id,
            title="Meeting",
            type="meeting",
            status="ready",
        )
        session.add(recording)
        await session.flush()
        seg = Segment(
            recording_id=recording.id,
            speaker="Anna",
            content="ship by Friday",
            start_ms=0,
            end_ms=1000,
            embedding=[0.0] * 1536,
        )
        session.add(seg)
        await session.flush()

        installer(str(seg.id))

        async def fake_generate(text: str) -> list[float]:
            return [0.0] * 1536

        monkeypatch.setattr(
            "app.core.qa.generate_embedding", fake_generate, raising=True
        )

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={"content": "what did Anna commit to?"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = response.text
        # SSE frames are `event: <name>\ndata: <json>\n\n`
        events = [
            line.split(": ", 1)[1]
            for line in body.split("\n")
            if line.startswith("event: ")
        ]
        assert "turn_start" in events
        assert "tool_call" in events
        assert "tool_result" in events
        assert "token" in events
        assert "citation" in events
        assert events[-1] == "done"
