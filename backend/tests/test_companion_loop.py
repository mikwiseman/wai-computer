"""Tests for Wai Companion's single Responses stream + remote MCP tool."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core import companion as companion_module
from app.core.companion import (
    ArtifactEvent,
    CompanionError,
    DoneEvent,
    PlanEvent,
    ThinkingEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnContext,
    run_turn,
    system_prompt_for,
)
from app.models.companion import ChatMessage, Conversation
from app.models.mcp_oauth import McpOAuthToken


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
class _OutputItemEvent:
    """A response.output_item.{added,done} streaming event carrying one output
    item — the shape hosted reads (mcp_call) and web_search_call arrive in."""

    item: dict[str, Any]
    type: str = "response.output_item.added"


@dataclass
class _ReasoningDeltaEvent:
    """A streamed reasoning-summary delta (the model's private thinking)."""

    delta: str
    type: str = "response.reasoning_summary_text.delta"


@dataclass
class _ErrorEvent:
    message: str
    type: str = "response.error"

    @property
    def error(self) -> dict[str, str]:
        return {"message": self.message}


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
        assert kwargs.get("stream") is True
        return _AsyncEventStream(self.events)


class _SeqOpenAI:
    """Like FakeOpenAI but returns a DIFFERENT event list per create() call, for
    testing the multi-step actions loop (each loop step is one create())."""

    def __init__(self, calls_events: list[list[Any]]):
        self._queue = list(calls_events)
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        events = self._queue.pop(0) if self._queue else []
        return _AsyncEventStream(events)


def _function_call_completed(name: str, arguments: str) -> "_CompletedEvent":
    return _CompletedEvent(
        _FakeResponse(
            output=[
                {
                    "type": "function_call",
                    "name": name,
                    "arguments": arguments,
                    "call_id": "call_1",
                    "id": "fc_1",
                }
            ],
            output_text="",
            usage=_Usage(input_tokens=5, output_tokens=2, cached_tokens=0),
        )
    )


def test_normalize_plan_steps_bounds_and_coerces():
    from app.core.companion import _normalize_plan_steps

    out = _normalize_plan_steps(
        [
            {"title": "  Search  ", "status": "done"},
            {"title": "", "status": "in_progress"},  # dropped: blank title
            {"title": "Summarize", "status": "bogus"},  # status coerced
            "not-a-dict",  # dropped
        ]
    )
    assert out == [
        {"title": "Search", "status": "done"},
        {"title": "Summarize", "status": "pending"},
    ]


@pytest_asyncio.fixture
async def setup_user_and_chat(db_session):
    from app.models.user import User

    user = User(email=f"u-{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.flush()

    return {"user": user, "conversation": conv}


async def _collect(it: AsyncIterator):
    return [e async for e in it]


def _completed(
    text: str = "Готово.",
    *,
    output: list[dict[str, Any]] | None = None,
) -> _CompletedEvent:
    return _CompletedEvent(
        _FakeResponse(
            output=output or [],
            output_text=text,
            usage=_Usage(input_tokens=11, output_tokens=7, cached_tokens=3),
        )
    )


class TestRunTurn:
    async def test_single_stream_uses_gpt55_with_remote_mcp_tool(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([
            _DeltaEvent("Нашёл это через Wai."),
            _completed("Нашёл это через Wai."),
        ])

        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "Что я обещал сделать?",
                openai_client=fake,
            )
        )

        assert isinstance(events[0], companion_module.TurnStartEvent)
        assert (
            "".join(e.text for e in events if isinstance(e, TokenEvent))
            == "Нашёл это через Wai."
        )
        assert isinstance(events[-1], DoneEvent)
        assert len(fake.calls) == 1

        call = fake.calls[0]
        assert call["model"] == "gpt-5.5"
        assert call["stream"] is True
        assert call["prompt_cache_key"] == f"wai-companion-{s['user'].id}"
        assert len(call["tools"]) == 1

        tool = call["tools"][0]
        assert tool["type"] == "mcp"
        assert tool["server_label"] == "wai"
        assert tool["server_url"].endswith("/mcp")
        assert tool["require_approval"] == "never"
        assert tool["allowed_tools"] == [
            "search",
            "fetch",
            "list_folders",
            "list_recordings",
            "list_action_items",
        ]
        assert tool["authorization"]
        assert not tool["authorization"].startswith("Bearer ")

        tokens = (
            await db_session.execute(
                select(McpOAuthToken).where(McpOAuthToken.user_id == s["user"].id)
            )
        ).scalars().all()
        assert len(tokens) == 1

        messages = (
            await db_session.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == s["conversation"].id
                )
            )
        ).scalars().all()
        assistant = next(m for m in messages if m.role == "assistant")
        assert assistant.model == "gpt-5.5"
        assert assistant.tool_calls is None
        assert assistant.input_tokens == 11
        assert assistant.output_tokens == 7
        assert assistant.cached_tokens == 3
        assert "Нашёл это через Wai." in str(assistant.content)
        assert tool["authorization"] not in str(assistant.content)

    async def test_cached_mcp_tool_list_is_reused_without_persisting_token(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        cached_tools = {
            "type": "mcp_list_tools",
            "server_label": "wai",
            "tools": [{"name": "search"}, {"name": "fetch"}],
        }
        first_fake = FakeOpenAI([
            _DeltaEvent("first"),
            _completed("first", output=[cached_tools]),
        ])
        second_fake = FakeOpenAI([_DeltaEvent("second"), _completed("second")])

        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "first question",
                openai_client=first_fake,
            )
        )
        await db_session.commit()
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "second question",
                openai_client=second_fake,
            )
        )

        second_input = second_fake.calls[0]["input"]
        assert second_input[0] == cached_tools
        first_token = first_fake.calls[0]["tools"][0]["authorization"]
        second_token = second_fake.calls[0]["tools"][0]["authorization"]
        assert first_token not in str(second_input)
        assert second_token not in str(second_input)

    async def test_session_developer_message_is_input_not_instructions(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([_DeltaEvent("ok"), _completed("ok")])

        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "О чем говорили вчера?",
                turn_context=TurnContext(
                    client_local_date="2026-05-18",
                    client_timezone="Europe/Reykjavik",
                ),
                openai_client=fake,
            )
        )

        first_input = fake.calls[0]["input"]
        assert first_input[0]["role"] == "developer"
        assert "2026-05-18" in first_input[0]["content"]
        assert "Europe/Reykjavik" in first_input[0]["content"]
        assert "2026-05-18" not in fake.calls[0]["instructions"]
        assert "Europe/Reykjavik" not in fake.calls[0]["instructions"]

    async def test_brain_scope_injects_approved_context(
        self, db_session, setup_user_and_chat
    ):
        from app.core import brain_spaces as brain_space_service

        s = setup_user_and_chat
        space = await brain_space_service.create_space(
            db_session,
            s["user"].id,
            name="Ops Brain",
        )
        await brain_space_service.create_page(
            db_session,
            actor_user_id=s["user"].id,
            space_id=space.id,
            title="Session rules",
            claims=[
                {
                    "kind": "workflow_rule",
                    "text": "Use 40 minute intro sessions.",
                    "confidence": 0.91,
                    "authority": "self",
                }
            ],
        )
        s["conversation"].scope = {"brain_space_id": str(space.id)}
        await db_session.flush()
        fake = FakeOpenAI([_DeltaEvent("ok"), _completed("ok")])

        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "What should I use?",
                openai_client=fake,
            )
        )

        first_input = fake.calls[0]["input"]
        assert first_input[0]["role"] == "developer"
        assert "scope: selected Brain" in first_input[0]["content"]
        assert "brain: Ops Brain; approved items: 1" in first_input[0]["content"]
        assert "<brain_context>" in first_input[0]["content"]
        assert "Use 40 minute intro sessions." in first_input[0]["content"]

    async def test_stream_error_surfaces_without_second_request(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([_ErrorEvent("upstream failed")])

        with pytest.raises(CompanionError) as exc:
            await _collect(
                run_turn(
                    db_session,
                    s["user"].id,
                    s["conversation"].id,
                    "hi",
                    openai_client=fake,
                )
            )
        assert exc.value.code == "stream_error"
        assert "upstream failed" in exc.value.message
        assert len(fake.calls) == 1

    async def test_completed_dict_response_can_supply_text_without_delta(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output_text": "",
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "from completed"}
                            ]
                        }
                    ],
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 2,
                        "input_tokens_details": {"cached_tokens": 4},
                    },
                },
            }
        ])

        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "hi",
                openai_client=fake,
            )
        )

        assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "from completed"
        done = events[-1]
        assert isinstance(done, DoneEvent)
        assert done.input_tokens == 5
        assert done.output_tokens == 2
        assert done.cached_tokens == 4

    async def test_incomplete_response_is_not_retried(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([
            {
                "type": "response.completed",
                "response": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                },
            }
        ])

        with pytest.raises(CompanionError) as exc:
            await _collect(
                run_turn(
                    db_session,
                    s["user"].id,
                    s["conversation"].id,
                    "hi",
                    openai_client=fake,
                )
            )
        assert exc.value.code == "model_incomplete"
        assert len(fake.calls) == 1

    async def test_empty_stream_response_is_error(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([_completed("")])

        with pytest.raises(CompanionError) as exc:
            await _collect(
                run_turn(
                    db_session,
                    s["user"].id,
                    s["conversation"].id,
                    "hi",
                    openai_client=fake,
                )
            )
        assert exc.value.code == "empty_model_output"

    async def test_error_dict_uses_default_message(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI([{"type": "error", "error": {}}])

        with pytest.raises(CompanionError) as exc:
            await _collect(
                run_turn(
                    db_session,
                    s["user"].id,
                    s["conversation"].id,
                    "hi",
                    openai_client=fake,
                )
            )
        assert exc.value.code == "stream_error"
        assert "Companion stream failed" in exc.value.message

    async def test_update_plan_tool_emits_plan_event(
        self, db_session, setup_user_and_chat
    ):
        """When the agent calls update_plan, a PlanEvent is streamed (live plan
        card) and the loop continues to do the real work — no approval gate."""
        s = setup_user_and_chat
        step1 = [
            _function_call_completed(
                "update_plan",
                '{"steps": [{"title": "Search", "status": "in_progress"}, '
                '{"title": "Summarize", "status": "pending"}]}',
            )
        ]
        step2 = [_DeltaEvent("Done."), _completed("Done.")]
        fake = _SeqOpenAI([step1, step2])
        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "summarize my pricing call and list follow-ups",
                openai_client=fake,
                enable_actions=True,
            )
        )
        plans = [e for e in events if isinstance(e, PlanEvent)]
        assert len(plans) == 1
        assert plans[0].steps == [
            {"title": "Search", "status": "in_progress"},
            {"title": "Summarize", "status": "pending"},
        ]
        assert isinstance(events[-1], DoneEvent)
        assistant = (
            await db_session.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == s["conversation"].id,
                    ChatMessage.role == "assistant",
                )
            )
        ).scalar_one()
        assert assistant.tool_calls == [
            {
                "type": "plan",
                "steps": [
                    {"title": "Search", "status": "in_progress"},
                    {"title": "Summarize", "status": "pending"},
                ],
            }
        ]

    async def test_create_artifact_tool_emits_artifact_event(
        self, db_session, setup_user_and_chat
    ):
        """create_artifact streams an ArtifactEvent (preview card) and the loop
        continues — auto-run, no approval gate."""
        s = setup_user_and_chat
        step1 = [
            _function_call_completed(
                "create_artifact",
                '{"title": "Landing", "kind": "html", '
                '"content": "<!doctype html><h1>Hi</h1>"}',
            )
        ]
        step2 = [_DeltaEvent("Done — see the artifact."), _completed("Done.")]
        fake = _SeqOpenAI([step1, step2])
        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "build a landing page",
                openai_client=fake,
                enable_actions=True,
            )
        )
        arts = [e for e in events if isinstance(e, ArtifactEvent)]
        assert len(arts) == 1
        assert arts[0].title == "Landing"
        assert arts[0].kind == "html"
        assert "<h1>Hi</h1>" in arts[0].content
        assert isinstance(events[-1], DoneEvent)
        assistant = (
            await db_session.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == s["conversation"].id,
                    ChatMessage.role == "assistant",
                )
            )
        ).scalar_one()
        assert assistant.tool_calls == [
            {
                "type": "artifact",
                "artifact_id": "call_1",
                "title": "Landing",
                "kind": "html",
                "content": "<!doctype html><h1>Hi</h1>",
                "language": "",
            }
        ]

    async def test_run_turn_streams_reasoning_as_thinking(
        self, db_session, setup_user_and_chat
    ):
        """With stream_reasoning the model's reasoning summary is forwarded as
        ThinkingEvent deltas (collapsible "Thinking" block) and reasoning is
        actually requested on the API call."""
        s = setup_user_and_chat
        fake = FakeOpenAI(
            [
                _ReasoningDeltaEvent("Checking the pricing call. "),
                _DeltaEvent("Found it."),
                _completed("Found it."),
            ]
        )
        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "what about pricing?",
                openai_client=fake,
                stream_reasoning=True,
            )
        )
        thinking = [e for e in events if isinstance(e, ThinkingEvent)]
        assert thinking and "pricing" in thinking[0].text
        assert fake.calls[0].get("reasoning") == {"summary": "auto"}

    async def test_default_run_turn_does_not_request_reasoning(
        self, db_session, setup_user_and_chat
    ):
        """The low-latency voice path (default) must not pay the reasoning tax."""
        s = setup_user_and_chat
        fake = FakeOpenAI([_DeltaEvent("Hi."), _completed("Hi.")])
        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "hi",
                openai_client=fake,
            )
        )
        assert "reasoning" not in fake.calls[0]

    async def test_run_turn_emits_tool_actions_for_mcp_reads(
        self, db_session, setup_user_and_chat
    ):
        """Hosted brain reads surface as live tool_call + tool_result events so
        the client can render a "Tool actions" card. The result summary is a
        privacy-safe count, never raw transcript content."""
        s = setup_user_and_chat
        fake = FakeOpenAI(
            [
                _OutputItemEvent(
                    item={
                        "type": "mcp_call",
                        "id": "mcp_1",
                        "name": "search",
                        "arguments": '{"query": "pricing"}',
                    }
                ),
                _DeltaEvent("Found it. "),
                _OutputItemEvent(
                    item={
                        "type": "mcp_call",
                        "id": "mcp_1",
                        "name": "search",
                        "output": '{"segments": [1, 2, 3]}',
                    },
                    type="response.output_item.done",
                ),
                _completed("Found it."),
            ]
        )
        events = await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "what about pricing?",
                openai_client=fake,
            )
        )
        types = [e.type for e in events]
        assert types[0] == "turn_start"
        assert types[-1] == "done"
        calls = [e for e in events if isinstance(e, ToolCallEvent)]
        results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(calls) == 1 and calls[0].tool == "search"
        assert calls[0].args == {"query": "pricing"}
        assert len(results) == 1 and results[0].ok is True
        assert "3 results" in results[0].summary
        assistant = (
            await db_session.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == s["conversation"].id,
                    ChatMessage.role == "assistant",
                )
            )
        ).scalar_one()
        assert assistant.tool_calls == [
            {
                "type": "tools",
                "actions": [
                    {
                        "call_id": "mcp_1",
                        "tool": "search",
                        "summary": "3 results",
                        "ok": True,
                    }
                ],
            }
        ]

    async def test_actions_loop_persists_tool_actions_for_mcp_reads(
        self, db_session, setup_user_and_chat
    ):
        s = setup_user_and_chat
        fake = FakeOpenAI(
            [
                _OutputItemEvent(
                    item={
                        "type": "mcp_call",
                        "id": "mcp_2",
                        "name": "search",
                        "arguments": '{"query": "pricing"}',
                    }
                ),
                _OutputItemEvent(
                    item={
                        "type": "mcp_call",
                        "id": "mcp_2",
                        "name": "search",
                        "output": '{"segments": [1, 2]}',
                    },
                    type="response.output_item.done",
                ),
                _DeltaEvent("Found it."),
                _completed("Found it."),
            ]
        )

        await _collect(
            run_turn(
                db_session,
                s["user"].id,
                s["conversation"].id,
                "what about pricing?",
                openai_client=fake,
                enable_actions=True,
            )
        )

        assistant = (
            await db_session.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == s["conversation"].id,
                    ChatMessage.role == "assistant",
                )
            )
        ).scalar_one()
        assert assistant.tool_calls == [
            {
                "type": "tools",
                "actions": [
                    {
                        "call_id": "mcp_2",
                        "tool": "search",
                        "summary": "2 results",
                        "ok": True,
                    }
                ],
            }
        ]

    async def test_system_prompt_points_to_mcp_not_private_function_tools(
        self, setup_user_and_chat
    ):
        prompt = system_prompt_for(setup_user_and_chat["user"])
        assert "WaiComputer MCP" in prompt
        assert "search_transcripts" not in prompt
        assert "get_recording_summary" not in prompt
        assert "Match the language" in prompt


@pytest_asyncio.fixture
async def stub_openai_for_route(monkeypatch):
    holder = {"runs": []}

    def install():
        async def fake_run_wai_run_inline(_db, run):
            holder["runs"].append(run)
            run.status = "done"
            run.result = {"output_text": "Found it."}
            return run

        monkeypatch.setattr(
            "app.api.routes.companion.run_wai_run_inline",
            fake_run_wai_run_inline,
            raising=True,
        )

    return install, holder


class TestPostMessageSSE:
    async def test_sse_event_protocol_end_to_end(
        self,
        client: AsyncClient,
        auth_headers: dict,
        stub_openai_for_route,
    ):
        install, holder = stub_openai_for_route
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        install()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={"content": "what did I promise?"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = response.text
        events = [
            line.split(": ", 1)[1]
            for line in body.split("\n")
            if line.startswith("event: ")
        ]
        assert events == ["turn_start", "token", "done"]
        assert "Found it." in body
        assert len(holder["runs"]) == 1

    async def test_legacy_wai_task_streams_and_persists_brain_citations(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session,
        monkeypatch,
    ):
        from app.models.recording import Recording, Segment
        from app.models.user import User

        user = (await db_session.execute(select(User))).scalars().one()
        recording = Recording(
            user_id=user.id,
            title="Roadmap review",
            type="meeting",
            status="ready",
        )
        db_session.add(recording)
        await db_session.flush()
        segment = Segment(
            recording_id=recording.id,
            content="The roadmap risk is hiring.",
            start_ms=42000,
            end_ms=46000,
        )
        db_session.add(segment)
        await db_session.flush()

        async def fake_run_wai_run_inline(_db, run):
            run.status = "done"
            run.result = {
                "output_text": "The roadmap risk is hiring [1]",
                "citations": [
                    {
                        "id": str(segment.id),
                        "source_kind": "recording",
                        "source_id": str(recording.id),
                        "title": "Roadmap review",
                        "start_ms": 42000,
                    }
                ],
                "gaps": [],
                "freshness": {
                    "newest_source_at": "2026-06-01T00:00:00+00:00",
                    "weeks_since": 0,
                    "stale": False,
                },
            }
            return run

        monkeypatch.setattr(
            "app.api.routes.companion.run_wai_run_inline",
            fake_run_wai_run_inline,
            raising=True,
        )
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={"content": "What is the roadmap risk?"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        events = [
            line.split(": ", 1)[1]
            for line in response.text.split("\n")
            if line.startswith("event: ")
        ]
        assert events == ["turn_start", "token", "citation", "done"]
        citation_payloads = [
            json.loads(line.split(": ", 1)[1])
            for line in response.text.split("\n")
            if line.startswith("data: ") and "recording_id" in line
        ]
        assert citation_payloads == [
            {
                "index": 1,
                "segment_id": str(segment.id),
                "recording_id": str(recording.id),
                "start_ms": 42000,
                "end_ms": None,
                "span_start": 27,
                "span_end": 30,
            }
        ]

        detail = await client.get(
            f"/api/companion/chats/{chat['id']}", headers=auth_headers
        )
        assert detail.status_code == 200
        assistant = [
            msg for msg in detail.json()["messages"] if msg["role"] == "assistant"
        ][-1]
        assert assistant["citations"][0]["segment_id"] == str(segment.id)
        assert assistant["citations"][0]["recording_id"] == str(recording.id)
        assert assistant["citations"][0]["span_start"] == 27
        assert assistant["citations"][0]["span_end"] == 30

    async def test_sse_actions_capability_enables_agentic_action_loop(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={
                "content": "send message hello",
                "client_capabilities": ["actions_v1"],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.text
        assert "event: action_proposed" in body
        assert "send_message_telegram" in body
        assert "linked chat" in body
        assert "hello" in body

    async def test_agent_chat_v2_streams_tool_actions_via_run_turn(
        self,
        client: AsyncClient,
        auth_headers: dict,
        monkeypatch,
    ):
        """A client advertising agent_chat_v2 is routed back through the
        streaming run_turn engine and receives live tool_call/tool_result
        events — the durable-runtime path would only emit a single message."""
        fake = FakeOpenAI(
            [
                _OutputItemEvent(
                    item={
                        "type": "mcp_call",
                        "id": "mcp_1",
                        "name": "search",
                        "arguments": '{"query": "pricing"}',
                    }
                ),
                _DeltaEvent("Here it is."),
                _OutputItemEvent(
                    item={
                        "type": "mcp_call",
                        "id": "mcp_1",
                        "output": '{"segments": [1, 2]}',
                    },
                    type="response.output_item.done",
                ),
                _completed("Here it is."),
            ]
        )
        monkeypatch.setattr(
            "app.core.companion.get_openai_client", lambda: fake
        )
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={
                "content": "what did I decide on pricing?",
                "client_capabilities": ["actions_v1", "agent_chat_v2"],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.text
        events = [
            line.split(": ", 1)[1]
            for line in body.split("\n")
            if line.startswith("event: ")
        ]
        assert events[0] == "turn_start"
        assert "tool_call" in events
        assert "tool_result" in events
        assert "done" in events

    async def test_agent_chat_v2_action_proposal_stores_visible_waiting_message(
        self,
        client: AsyncClient,
        auth_headers: dict,
        monkeypatch,
    ):
        fake = _SeqOpenAI(
            [
                [
                    _function_call_completed(
                        "request_tool_group",
                        '{"group": "telegram"}',
                    )
                ],
                [
                    _function_call_completed(
                        "send_message_telegram",
                        '{"text": "late"}',
                    )
                ],
            ]
        )
        monkeypatch.setattr(
            "app.core.companion.get_openai_client", lambda: fake
        )
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={
                "content": "message me that I am late",
                "client_capabilities": ["actions_v1", "agent_chat_v2"],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.text
        events = [
            line.split(": ", 1)[1]
            for line in body.split("\n")
            if line.startswith("event: ")
        ]
        assert "action_proposed" in events
        assert "token" in events
        assert "Waiting for your approval" in body

        detail = await client.get(
            f"/api/companion/chats/{chat['id']}", headers=auth_headers
        )
        assert detail.status_code == 200
        assistant_messages = [
            m for m in detail.json()["messages"] if m["role"] == "assistant"
        ]
        assert assistant_messages
        assert (
            assistant_messages[-1]["content"][0]["text"]
            == "Waiting for your approval: Send a Telegram message to you: “late”"
        )

    async def test_agent_chat_v2_action_proposal_waiting_message_matches_russian(
        self,
        client: AsyncClient,
        auth_headers: dict,
        monkeypatch,
    ):
        fake = _SeqOpenAI(
            [
                [
                    _function_call_completed(
                        "request_tool_group",
                        '{"group": "telegram"}',
                    )
                ],
                [
                    _function_call_completed(
                        "send_message_telegram",
                        '{"text": "я опаздываю"}',
                    )
                ],
            ]
        )
        monkeypatch.setattr(
            "app.core.companion.get_openai_client", lambda: fake
        )
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={
                "content": "напиши мне, что я опаздываю",
                "client_capabilities": ["actions_v1", "agent_chat_v2"],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        payloads = [
            json.loads(line.split(": ", 1)[1])
            for line in response.text.split("\n")
            if line.startswith("data: ")
        ]
        assert any(
            payload.get("text", "").startswith("Жду твоего подтверждения")
            for payload in payloads
        )
        detail = await client.get(
            f"/api/companion/chats/{chat['id']}", headers=auth_headers
        )
        assert detail.status_code == 200
        assistant_messages = [
            m for m in detail.json()["messages"] if m["role"] == "assistant"
        ]
        assert assistant_messages[-1]["content"][0]["text"] == (
            "Жду твоего подтверждения: "
            "Send a Telegram message to you: “я опаздываю”"
        )

    async def test_first_user_message_auto_titles_new_chat(
        self,
        client: AsyncClient,
        auth_headers: dict,
        stub_openai_for_route,
    ):
        install, _ = stub_openai_for_route
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        install()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={
                "content": "Summarize my pricing call and list the open follow-ups"
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

        detail = await client.get(
            f"/api/companion/chats/{chat['id']}", headers=auth_headers
        )
        assert detail.status_code == 200
        assert (
            detail.json()["title"]
            == "Summarize my pricing call and list the open follow-ups"
        )

    async def test_auto_title_does_not_overwrite_manual_chat_title(
        self,
        client: AsyncClient,
        auth_headers: dict,
        stub_openai_for_route,
    ):
        install, _ = stub_openai_for_route
        chat = (
            await client.post(
                "/api/companion/chats", json={}, headers=auth_headers
            )
        ).json()
        renamed = await client.patch(
            f"/api/companion/chats/{chat['id']}",
            json={"title": "Manual title"},
            headers=auth_headers,
        )
        assert renamed.status_code == 200
        install()

        response = await client.post(
            f"/api/companion/chats/{chat['id']}/messages",
            json={"content": "This prompt must not replace the manual title"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        detail = await client.get(
            f"/api/companion/chats/{chat['id']}", headers=auth_headers
        )
        assert detail.status_code == 200
        assert detail.json()["title"] == "Manual title"
