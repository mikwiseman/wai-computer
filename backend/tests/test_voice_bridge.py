"""Unit tests for the ElevenLabs Custom-LLM SSE re-framing core."""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.companion import (
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolCallEvent,
)
from app.core.voice_bridge import (
    CHAT_COMPLETION_CHUNK_OBJECT,
    VoiceChatCompletionRequest,
    VoiceChatMessage,
    chat_completion_chunk,
    to_chat_completion_sse,
)


async def _aiter(events: list[Any]) -> AsyncIterator[Any]:
    for event in events:
        yield event


def _data(line: str) -> Any:
    """Parse the JSON payload of a `data: {json}\\n\\n` SSE line."""
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    body = line[len("data: ") : -2]
    return body if body == "[DONE]" else json.loads(body)


async def _collect(events: list[Any], response_id: str = "chatcmpl-test") -> list[Any]:
    return [
        _data(line)
        async for line in to_chat_completion_sse(_aiter(events), response_id=response_id)
    ]


def test_chunk_shape_is_minimal_openai_chunk():
    parsed = json.loads(
        chat_completion_chunk("id-1", {"content": "hi"}, finish_reason=None)[
            len("data: ") : -2
        ]
    )
    assert parsed["id"] == "id-1"
    assert parsed["object"] == CHAT_COMPLETION_CHUNK_OBJECT
    assert parsed["choices"][0]["delta"] == {"content": "hi"}
    assert parsed["choices"][0]["finish_reason"] is None


async def test_happy_path_emits_role_content_stop_then_done():
    out = await _collect([TokenEvent(text="Hi "), TokenEvent(text="there."), DoneEvent()])
    # Leading role chunk, two content chunks, a stop chunk, then [DONE].
    assert out[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert out[1]["choices"][0]["delta"] == {"content": "Hi "}
    assert out[2]["choices"][0]["delta"] == {"content": "there."}
    assert out[3]["choices"][0]["delta"] == {}
    assert out[3]["choices"][0]["finish_reason"] == "stop"
    assert out[-1] == "[DONE]"


async def test_empty_token_is_not_emitted():
    out = await _collect([TokenEvent(text=""), TokenEvent(text="x"), DoneEvent()])
    contents = [
        c["choices"][0]["delta"].get("content")
        for c in out
        if isinstance(c, dict) and "content" in c["choices"][0]["delta"]
    ]
    assert contents == ["x"]


async def test_non_text_events_are_skipped():
    out = await _collect(
        [
            ToolCallEvent(),
            TokenEvent(text="answer"),
            CitationEvent(),
            DoneEvent(),
        ]
    )
    deltas = [c["choices"][0]["delta"] for c in out if isinstance(c, dict)]
    assert {"role": "assistant"} in deltas
    assert {"content": "answer"} in deltas
    # No citation/tool content leaked into the spoken stream.
    assert all("citation" not in str(d) for d in deltas)


async def test_error_event_surfaces_error_and_stops_without_done():
    out = await _collect([TokenEvent(text="partial"), ErrorEvent(code="rate_limited")])
    # role, content, then an error line — and crucially NO [DONE] after an error.
    assert out[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert out[1]["choices"][0]["delta"] == {"content": "partial"}
    assert out[-1] == {"error": {"code": "rate_limited"}}
    assert "[DONE]" not in out


async def test_no_tokens_still_emits_valid_empty_completion():
    out = await _collect([DoneEvent()])
    assert out[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert out[1]["choices"][0]["finish_reason"] == "stop"
    assert out[-1] == "[DONE]"


def test_latest_user_message_picks_last_user_turn():
    req = VoiceChatCompletionRequest.model_validate(
        {
            "model": "wai",
            "messages": [
                {"role": "system", "content": "you are wai"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "  what did I decide?  "},
            ],
        }
    )
    assert req.latest_user_message() == "what did I decide?"
    assert req.stream is True  # default


def test_latest_user_message_none_when_no_user_turn():
    req = VoiceChatCompletionRequest(
        messages=[VoiceChatMessage(role="system", content="hi")]
    )
    assert req.latest_user_message() is None


def test_latest_user_message_none_when_blank():
    req = VoiceChatCompletionRequest(
        messages=[VoiceChatMessage(role="user", content="   ")]
    )
    assert req.latest_user_message() is None
