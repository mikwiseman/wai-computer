"""Tests for Wai Companion's single Responses stream + remote MCP tool."""

from __future__ import annotations

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
    CompanionError,
    DoneEvent,
    TokenEvent,
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
        assert len(call["tools"]) == 2

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
        assert call["tools"][1] == {"type": "web_search"}

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

    async def test_system_prompt_points_to_mcp_not_private_function_tools(
        self, setup_user_and_chat
    ):
        prompt = system_prompt_for(setup_user_and_chat["user"])
        assert "WaiComputer MCP" in prompt
        assert "search_transcripts" not in prompt
        assert "get_recording_summary" not in prompt
        assert "Match the language" in prompt
        assert "general questions" in prompt
        assert "When the corpus is silent, say so in one sentence and stop" not in prompt


@pytest_asyncio.fixture
async def stub_openai_for_route(monkeypatch):
    holder = {"fake": None}

    def install() -> FakeOpenAI:
        fake = FakeOpenAI([_DeltaEvent("Found it."), _completed("Found it.")])
        holder["fake"] = fake
        monkeypatch.setattr(
            "app.core.companion.get_openai_client",
            lambda: fake,
            raising=True,
        )
        return fake

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
        assert holder["fake"] is not None
        assert len(holder["fake"].calls) == 1

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
