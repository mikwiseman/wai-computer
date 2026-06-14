"""Coverage push for app/core/companion.py — tool bodies, scope context, stream edges.

Targets: _tool_search_transcripts happy path (816-845), _tool_search_people
(1199-1245), _tool_remember rejection (1293-1303), brain/entity scope context
(1558-1616), dict-shaped stream events in the actions loop (2548-2576), and the
streamed tool-item helpers (2989-3056).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import brain_spaces as brain_space_service
from app.core import companion as companion_module
from app.core import user_memory as user_memory_module
from app.core.companion import (
    CompanionError,
    DoneEvent,
    ThinkingEvent,
    TokenEvent,
    run_turn,
)
from app.models.companion import Conversation
from app.models.entity import Entity, EntityRelation
from app.models.recording import Recording, Segment
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def user_conv(db_session):
    user = User(email=f"comp-cov-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()
    return user.id, conv.id


class _AsyncEventStream:
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
        return _AsyncEventStream(self.events)


async def _collect(it: AsyncIterator) -> list:
    return [e async for e in it]


def _dict_completed(
    text: str = "Done.", *, status: str = "completed"
) -> dict[str, Any]:
    return {
        "type": "response.completed",
        "response": {
            "status": status,
            "output_text": text,
            "output": [],
            "usage": {"input_tokens": 4, "output_tokens": 2},
        },
    }


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------


def test_scope_entity_uuid_paths():
    entity_id = uuid4()
    assert companion_module._scope_entity_uuid(None) is None
    assert companion_module._scope_entity_uuid({"entity_id": ""}) is None
    assert companion_module._scope_entity_uuid({"entity_id": str(entity_id)}) == entity_id
    with pytest.raises(CompanionError) as exc_info:
        companion_module._scope_entity_uuid({"entity_id": "broken"})
    assert exc_info.value.code == "invalid_scope"


def test_format_scope_for_session_mentions_entity_page():
    label = companion_module._format_scope_for_session(
        {"entity_id": str(uuid4()), "recording_ids": [str(uuid4())]}
    )
    assert label == "a Brain page + 1 pinned recording"


async def test_has_searchable_segments_empty_scope_short_circuits(db_session, user_conv):
    user_id, _ = user_conv
    assert (
        await companion_module._has_searchable_transcript_segments(db_session, user_id, [])
        is False
    )
    assert (
        await companion_module._has_searchable_transcript_segments(
            db_session, user_id, [uuid4()]
        )
        is False
    )


# ---------------------------------------------------------------------------
# Tool bodies
# ---------------------------------------------------------------------------


async def test_tool_search_transcripts_returns_citable_segments(
    db_session, user_conv, monkeypatch
):
    user_id, _ = user_conv
    recording = Recording(user_id=user_id, title="Standup", type="meeting", status="ready")
    db_session.add(recording)
    await db_session.flush()
    segment = Segment(
        recording_id=recording.id,
        content="We shipped the beta on Friday.",
        speaker="Anna",
        raw_label="S1",
        start_ms=0,
        end_ms=4000,
        confidence=0.9,
    )
    db_session.add(segment)
    await db_session.flush()

    async def fake_retrieve(db, uid, query, recording_ids=None, limit=15):
        assert query == "beta launch"
        return [
            SimpleNamespace(
                id=segment.id,
                recording_id=recording.id,
                recording_title="Standup",
                speaker="Anna",
                content="We shipped the beta on Friday.",
                start_ms=0,
                end_ms=4000,
            )
        ]

    monkeypatch.setattr(companion_module, "retrieve_context", fake_retrieve)

    result = await companion_module._tool_search_transcripts(
        db_session, user_id, {"query": "beta launch"}, None
    )
    assert result.summary_for_event == "1 segments"
    payload = result.payload_for_model["segments"]
    assert payload[0]["recording_title"] == "Standup"
    assert payload[0]["snippet"] == "We shipped the beta on Friday."
    assert str(segment.id) in result.citable_segments


async def test_tool_search_people_returns_linked_recordings(db_session, user_conv):
    user_id, _ = user_conv
    anna = Entity(user_id=user_id, type="person", name="Anna Kovach")
    boris = Entity(user_id=user_id, type="person", name="Boris")
    recording = Recording(user_id=user_id, title="1:1 with Anna", type="meeting", status="ready")
    db_session.add_all([anna, boris, recording])
    await db_session.flush()
    db_session.add(
        EntityRelation(
            source_id=anna.id,
            target_id=boris.id,
            relation_type="mentioned_in",
            recording_id=recording.id,
        )
    )
    await db_session.flush()

    result = await companion_module._tool_search_people(
        db_session, user_id, {"name": "anna"}, None
    )
    assert result.summary_for_event == "1 recordings"
    recordings = result.payload_for_model["recordings"]
    assert recordings[0]["id"] == str(recording.id)
    assert str(anna.id) in result.payload_for_model["matched_entities"]


async def test_tool_search_people_entity_without_recordings(db_session, user_conv):
    user_id, _ = user_conv
    ghost = Entity(user_id=user_id, type="person", name="Ghost Person")
    db_session.add(ghost)
    await db_session.flush()

    result = await companion_module._tool_search_people(
        db_session, user_id, {"name": "Ghost"}, None
    )
    assert result.summary_for_event == "0 recordings"
    assert result.payload_for_model["recordings"] == []
    assert result.payload_for_model["matched_entities"] == [str(ghost.id)]


async def test_tool_search_people_scope_filters_recordings(db_session, user_conv):
    user_id, _ = user_conv
    anna = Entity(user_id=user_id, type="person", name="Scoped Anna")
    other = Entity(user_id=user_id, type="person", name="Other")
    recording = Recording(user_id=user_id, title="Scoped", type="meeting", status="ready")
    db_session.add_all([anna, other, recording])
    await db_session.flush()
    db_session.add(
        EntityRelation(
            source_id=anna.id,
            target_id=other.id,
            relation_type="mentioned_in",
            recording_id=recording.id,
        )
    )
    await db_session.flush()

    result = await companion_module._tool_search_people(
        db_session,
        user_id,
        {"name": "Scoped Anna"},
        {"recording_ids": [str(uuid4())]},  # scope excludes the linked recording
    )
    assert result.summary_for_event == "0 recordings"
    assert result.payload_for_model["recordings"] == []


async def test_tool_remember_surfaces_memory_rejection(db_session, user_conv, monkeypatch):
    user_id, conv_id = user_conv

    async def fake_write_block(*_args, **_kwargs):
        raise user_memory_module.MemoryError("block too large")

    monkeypatch.setattr(user_memory_module, "write_block", fake_write_block)

    result = await companion_module._tool_remember(
        db_session,
        user_id,
        {"block": "facts", "operation": "append", "content": "x"},
        None,
        conversation_id=conv_id,
    )
    assert result.summary_for_event == "memory write rejected"
    assert result.payload_for_model == {
        "ok": False,
        "reason": "memory_write_rejected",
        "detail": "block too large",
    }


async def test_tool_remember_reports_new_block_length(db_session, user_conv, monkeypatch):
    user_id, conv_id = user_conv

    async def fake_write_block(*_args, **_kwargs):
        return SimpleNamespace(after="stored fact line")

    monkeypatch.setattr(user_memory_module, "write_block", fake_write_block)

    result = await companion_module._tool_remember(
        db_session,
        user_id,
        {"block": "facts", "operation": "append", "content": "stored fact line"},
        None,
        conversation_id=conv_id,
    )
    assert result.summary_for_event == "updated memory block: facts"
    assert result.payload_for_model["ok"] is True
    assert result.payload_for_model["new_length_chars"] == len("stored fact line")


# ---------------------------------------------------------------------------
# Brain / entity scope context
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        brain_space_service.BrainSpaceNotFoundError("missing"),
        brain_space_service.BrainSpacePermissionError("denied"),
        brain_space_service.BrainSpaceValidationError("bad space"),
    ],
)
async def test_brain_context_maps_space_errors_to_invalid_scope(
    db_session, user_conv, monkeypatch, error
):
    user_id, _ = user_conv

    async def fake_build_context(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(brain_space_service, "build_context", fake_build_context)

    with pytest.raises(CompanionError) as exc_info:
        await companion_module._brain_context_for_scope(
            db_session, user_id, {"brain_space_id": str(uuid4())}
        )
    assert exc_info.value.code == "invalid_scope"


async def test_entity_scope_builds_dossier_context(db_session, user_conv, monkeypatch):
    user_id, _ = user_conv
    page = SimpleNamespace(
        name="Project Atlas",
        type="project",
        overview="Atlas is the Q3 launch.",
        facts=[SimpleNamespace(text="Anna owns rollout."), SimpleNamespace(text=None)],
        timeline=[
            SimpleNamespace(title="Kickoff", description="First sync."),
            SimpleNamespace(title="Security review", description=None),
            SimpleNamespace(title=None, description="dropped"),
        ],
        questions=[SimpleNamespace(text="Who signs off?")],
    )

    async def fake_ensure(_db, _uid, _eid):
        return page

    import app.core.entity_page_synthesis as entity_page_synthesis

    monkeypatch.setattr(entity_page_synthesis, "ensure_entity_page", fake_ensure)

    context = await companion_module._brain_context_for_scope(
        db_session, user_id, {"entity_id": str(uuid4())}
    )
    assert context["space"].name == "Project Atlas"
    assert context["claim_count"] == 2
    markdown = context["markdown"]
    assert markdown.startswith("# Project Atlas (project)")
    assert "## Facts" in markdown
    assert "- Anna owns rollout." in markdown
    assert "- Kickoff — First sync." in markdown
    assert "- Security review" in markdown
    assert "## Open questions" in markdown


async def test_entity_scope_without_page_raises_invalid_scope(
    db_session, user_conv, monkeypatch
):
    user_id, _ = user_conv

    async def fake_ensure(_db, _uid, _eid):
        return None

    import app.core.entity_page_synthesis as entity_page_synthesis

    monkeypatch.setattr(entity_page_synthesis, "ensure_entity_page", fake_ensure)

    with pytest.raises(CompanionError) as exc_info:
        await companion_module._brain_context_for_scope(
            db_session, user_id, {"entity_id": str(uuid4())}
        )
    assert exc_info.value.code == "invalid_scope"


# ---------------------------------------------------------------------------
# Actions loop: dict-shaped stream events
# ---------------------------------------------------------------------------


async def test_actions_loop_handles_dict_events_and_reasoning_delta(
    db_session, user_conv
):
    uid, cid = user_conv
    fake = FakeOpenAI(
        [
            {"type": "response.reasoning_summary_text.delta", "delta": "thinking..."},
            {"type": "response.output_text.delta", "delta": "Done."},
            _dict_completed("Done."),
        ]
    )
    events = await _collect(
        run_turn(db_session, uid, cid, "что нового?", openai_client=fake, enable_actions=True)
    )
    thinking = [e for e in events if isinstance(e, ThinkingEvent)]
    assert [t.text for t in thinking] == ["thinking..."]
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "Done."
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.input_tokens == 4


async def test_actions_loop_incomplete_response_raises_model_incomplete(
    db_session, user_conv
):
    uid, cid = user_conv
    fake = FakeOpenAI([_dict_completed("", status="incomplete")])
    with pytest.raises(CompanionError) as exc_info:
        await _collect(
            run_turn(db_session, uid, cid, "hello", openai_client=fake, enable_actions=True)
        )
    assert exc_info.value.code == "model_incomplete"


async def test_actions_loop_dict_error_event_raises_stream_error(db_session, user_conv):
    uid, cid = user_conv
    fake = FakeOpenAI([{"type": "response.error", "error": {"message": "boom"}}])
    with pytest.raises(CompanionError) as exc_info:
        await _collect(
            run_turn(db_session, uid, cid, "hello", openai_client=fake, enable_actions=True)
        )
    assert exc_info.value.code == "stream_error"
    assert "boom" in exc_info.value.message


# ---------------------------------------------------------------------------
# Streamed tool-item helpers (pure)
# ---------------------------------------------------------------------------


def test_tool_call_event_from_item_argument_shapes():
    assert companion_module._tool_call_event_from_item(None) is None
    assert (
        companion_module._tool_call_event_from_item({"type": "message", "id": "x"}) is None
    )

    bad_json = companion_module._tool_call_event_from_item(
        {"type": "mcp_call", "id": "c1", "name": "search", "arguments": "{not json"}
    )
    assert bad_json.args == {}

    dict_args = companion_module._tool_call_event_from_item(
        {"type": "mcp_call", "id": "c2", "name": "search", "arguments": {"q": "x"}}
    )
    assert dict_args.args == {"q": "x"}
    assert dict_args.tool == "search"


def test_tool_result_event_from_item_paths():
    assert companion_module._tool_result_event_from_item(None) is None
    failed = companion_module._tool_result_event_from_item(
        {"type": "mcp_call", "id": "c3", "error": "nope", "output": None}
    )
    assert failed.ok is False
    assert failed.summary == "Failed"
    invalid = companion_module._tool_result_event_from_item(
        {"type": "mcp_call", "id": "c4", "output": "not json"}
    )
    assert invalid.ok is False
    assert invalid.summary == "Tool returned invalid JSON"


def test_summarize_tool_output_shapes():
    assert companion_module._summarize_tool_output("oops", ok=False) == "Failed"
    assert (
        companion_module._summarize_tool_output("not json", ok=True)
        == "Tool returned invalid JSON"
    )
    assert (
        companion_module._summarize_tool_output('{"segments": [1, 2]}', ok=True)
        == "2 results"
    )
    assert companion_module._summarize_tool_output([1], ok=True) == "1 result"
    assert companion_module._summarize_tool_output({"other": 1}, ok=True) == "Completed"


def test_extract_text_from_object_output_items():
    item = SimpleNamespace(
        content=[
            SimpleNamespace(type="output_text", text="object "),
            SimpleNamespace(type="other", text="ignored"),
        ]
    )
    response = SimpleNamespace(output_text=None, output=[item, {"content": [
        {"type": "output_text", "text": "dict"}
    ]}])
    assert companion_module._extract_text(response) == "object dict"
