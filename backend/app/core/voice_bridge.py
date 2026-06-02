"""ElevenLabs Custom-LLM bridge: re-frame a ``run_turn`` event stream as an
OpenAI-compatible Chat Completions SSE stream.

ElevenLabs Agents call a custom LLM over an OpenAI-compatible
``/v1/chat/completions`` endpoint and expect Server-Sent Events whose chunks are
``chat.completion.chunk`` objects, ending with ``data: [DONE]``. We own the
brain (``run_turn``), so this module is the pure translation layer: it forwards
only user-facing assistant text (``TokenEvent``) as ``delta.content`` chunks and
drops tool/citation/approval events, matching ElevenLabs' documented pattern for
bridging a stateful agent ("forward only model text, skip tool/empty events").

This is decision-independent transport: no auth, no conversation resolution, no
brain configuration. Those live in the route. Keeping the re-framing here makes
the exact wire shape unit-testable without HTTP or a real model.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from app.core.companion import ErrorEvent, TokenEvent

CHAT_COMPLETION_CHUNK_OBJECT = "chat.completion.chunk"


class VoiceChatMessage(BaseModel):
    """One message in an ElevenLabs custom-LLM request. Content is a plain
    string for voice (no multi-part); unknown roles are tolerated."""

    role: str
    content: str = ""


class VoiceChatCompletionRequest(BaseModel):
    """The OpenAI-compatible Chat Completions request body ElevenLabs posts to a
    custom-LLM endpoint. We accept the documented fields and ignore the rest;
    only the latest user turn drives the brain (run_turn owns conversation
    history), matching ElevenLabs' stateful-agent bridging pattern."""

    messages: list[VoiceChatMessage] = Field(default_factory=list)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = True
    user_id: str | None = None

    def latest_user_message(self) -> str | None:
        """The most recent user turn's text, or None if there is no user
        message (e.g. an agent-initiated greeting request)."""
        for message in reversed(self.messages):
            if message.role == "user":
                text = message.content.strip()
                return text or None
        return None


def chat_completion_chunk(
    response_id: str,
    delta: dict[str, Any],
    *,
    finish_reason: str | None = None,
) -> str:
    """One SSE line: a minimal ``chat.completion.chunk`` ElevenLabs accepts.

    Shape per ElevenLabs' custom-LLM guide — id, object, and a single choice
    with the delta and finish_reason. No model/usage fields are required.
    """
    payload = {
        "id": response_id,
        "object": CHAT_COMPLETION_CHUNK_OBJECT,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


DONE_LINE = "data: [DONE]\n\n"


async def to_chat_completion_sse(
    events: AsyncIterator[Any],
    *,
    response_id: str,
) -> AsyncIterator[str]:
    """Translate a ``run_turn`` event stream into Chat Completions SSE lines.

    Emits a leading ``role: assistant`` chunk, then one ``content`` chunk per
    non-empty ``TokenEvent``; all other event types (tool calls, citations,
    proposed actions, narration, desktop actions, turn-start, done metadata) are
    dropped — ElevenLabs speaks only the assistant text. On normal completion a
    final empty chunk with ``finish_reason="stop"`` is sent, followed by
    ``[DONE]``. An ``ErrorEvent`` surfaces as an OpenAI-style error chunk and
    ends the stream — we never fabricate an answer (no silent fallback).
    """
    # OpenAI's first streamed chunk always carries the role.
    yield chat_completion_chunk(response_id, {"role": "assistant"})

    async for event in events:
        if isinstance(event, TokenEvent):
            if event.text:
                yield chat_completion_chunk(response_id, {"content": event.text})
        elif isinstance(event, ErrorEvent):
            # Surface the failure to ElevenLabs and stop; do not emit [DONE]
            # after an error (the turn did not complete normally). Shape per the
            # custom-LLM guide's error path: a bare `data: {error}` line.
            yield (
                "data: "
                + json.dumps({"error": {"code": event.code}}, ensure_ascii=False)
                + "\n\n"
            )
            return
        # All other events are non-spoken and intentionally skipped.

    yield chat_completion_chunk(response_id, {}, finish_reason="stop")
    yield DONE_LINE
