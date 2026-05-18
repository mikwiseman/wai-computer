"""Wai Companion service: agentic tool loop + structured synthesis.

Phase A: the model is given `search_transcripts`, `get_recording_summary`,
and `list_recordings` tools. It drives retrieval freely (up to TOOL_CALL_CAP
calls) and then emits a text-only response signalling the search is done.

Phase B: a single follow-up Responses API call with `response_format` set to
a strict JSON schema asks the model to write the final answer, with citations
as a typed list. The server validates every citation's `segment_id` against
the allowlist (the union of segment_ids returned by every `search_transcripts`
call in Phase A) and drops any that don't match — no retry, no fallback.

The service is an async iterator that yields `CompanionEvent` objects so the
SSE route is a thin adapter and tests can drive the service synchronously
with a mocked OpenAI client.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.openai_client import get_openai_client
from app.core.qa import SourceSegment, retrieve_context
from app.models.companion import ChatMessage, Conversation, MessageCitation
from app.models.recording import Recording, Summary

logger = logging.getLogger(__name__)

TOOL_CALL_CAP = 6
HISTORY_WINDOW = 20
SNIPPET_CHAR_CAP = 400

SYSTEM_PROMPT = (
    "You are Wai, a calm, precise partner — not an assistant, not a chatbot. "
    "You answer questions over the user's recorded conversations and notes. "
    "You cite specific moments using inline [n] markers tied to the citations "
    "list in your structured response. "
    "Do not start with 'Sure!', 'I'd be happy to', or any acknowledgement. "
    "Do not use emojis unless the user does first. "
    "Do not narrate your reasoning or say 'based on the transcripts'. "
    "When the corpus is silent on a question, say so in one sentence and stop. "
    "Default to one paragraph; use bullets only when the answer is a list."
)


# ---------- Event types yielded by run_turn ----------


@dataclass(frozen=True)
class TurnStartEvent:
    type: Literal["turn_start"] = "turn_start"
    message_id: str = ""
    conversation_id: str = ""


@dataclass(frozen=True)
class ToolCallEvent:
    type: Literal["tool_call"] = "tool_call"
    call_id: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResultEvent:
    type: Literal["tool_result"] = "tool_result"
    call_id: str = ""
    summary: str = ""


@dataclass(frozen=True)
class TokenEvent:
    type: Literal["token"] = "token"
    text: str = ""


@dataclass(frozen=True)
class CitationEvent:
    type: Literal["citation"] = "citation"
    index: int = 0
    segment_id: str = ""
    recording_id: str = ""
    start_ms: int | None = None
    end_ms: int | None = None
    span_start: int = 0
    span_end: int = 0


@dataclass(frozen=True)
class DoneEvent:
    type: Literal["done"] = "done"
    message_id: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    model: str = ""
    latency_ms: int = 0


@dataclass(frozen=True)
class ErrorEvent:
    type: Literal["error"] = "error"
    code: str = ""
    message: str = ""


CompanionEvent = (
    TurnStartEvent
    | ToolCallEvent
    | ToolResultEvent
    | TokenEvent
    | CitationEvent
    | DoneEvent
    | ErrorEvent
)


class CompanionError(Exception):
    """Raised when a turn cannot complete (model error, validator rejection)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------- Tool definitions advertised to the model ----------


def tool_definitions() -> list[dict[str, Any]]:
    """OpenAI Responses-API tool schemas."""
    return [
        {
            "type": "function",
            "name": "search_transcripts",
            "description": (
                "Search the user's recorded conversation transcripts. The "
                "only retrieval primitive that returns segment_ids; you may "
                "ONLY cite segment_ids returned by this tool."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 30},
                    "recording_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": "get_recording_summary",
            "description": (
                "Fetch the pre-extracted summary (key points, decisions, "
                "action items, topics) for a specific recording. Output is "
                "context-only — segment_ids in it cannot be cited."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "recording_id": {"type": "string"},
                },
                "required": ["recording_id"],
            },
        },
        {
            "type": "function",
            "name": "list_recordings",
            "description": (
                "List recordings created within a date range. Use to find "
                "the right recording before searching it; output is "
                "context-only and cannot be cited."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "date_from": {"type": "string", "format": "date-time"},
                    "date_to": {"type": "string", "format": "date-time"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
        },
    ]


def final_answer_schema() -> dict[str, Any]:
    """Phase-B structured output schema for the final answer."""
    return {
        "name": "wai_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "markdown": {"type": "string"},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "index": {"type": "integer", "minimum": 1},
                            "segment_id": {"type": "string"},
                            "span_start": {"type": "integer", "minimum": 0},
                            "span_end": {"type": "integer", "minimum": 0},
                        },
                        "required": [
                            "index",
                            "segment_id",
                            "span_start",
                            "span_end",
                        ],
                    },
                },
            },
            "required": ["markdown", "citations"],
        },
    }


# ---------- Tool implementations (server-side) ----------


@dataclass
class ToolExecutionResult:
    """A tool's output, plus any segment_ids that may be cited."""

    summary_for_event: str  # privacy-safe one-liner sent over SSE
    payload_for_model: Any  # full structured output sent back to the model
    citable_segments: dict[str, SourceSegment]  # keyed by segment_id (str)


async def _tool_search_transcripts(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    query = args["query"]
    k = args.get("k", 15)
    explicit_recording_ids = args.get("recording_ids")

    recording_ids: list[uuid.UUID] | None = None
    if explicit_recording_ids:
        recording_ids = [uuid.UUID(r) for r in explicit_recording_ids]
    elif scope and scope.get("recording_ids"):
        recording_ids = [uuid.UUID(r) for r in scope["recording_ids"]]

    rows = await retrieve_context(
        db, user_id, query, recording_ids=recording_ids, limit=k
    )

    citable: dict[str, SourceSegment] = {}
    items_for_model: list[dict[str, Any]] = []
    for row in rows:
        seg = SourceSegment(
            segment_id=str(row.id),
            recording_id=str(row.recording_id),
            recording_title=row.recording_title,
            speaker=row.speaker,
            content=row.content,
            start_ms=row.start_ms,
            end_ms=row.end_ms,
        )
        citable[seg.segment_id] = seg
        items_for_model.append(
            {
                "segment_id": seg.segment_id,
                "recording_id": seg.recording_id,
                "recording_title": seg.recording_title,
                "speaker": seg.speaker,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "snippet": (seg.content or "")[:SNIPPET_CHAR_CAP],
            }
        )

    return ToolExecutionResult(
        summary_for_event=f"{len(items_for_model)} segments",
        payload_for_model={"segments": items_for_model},
        citable_segments=citable,
    )


async def _tool_get_recording_summary(
    db: AsyncSession, user_id: uuid.UUID, args: dict[str, Any]
) -> ToolExecutionResult:
    recording_id = uuid.UUID(args["recording_id"])
    stmt = (
        select(Summary, Recording)
        .join(Recording, Summary.recording_id == Recording.id)
        .where(
            and_(
                Summary.recording_id == recording_id,
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        return ToolExecutionResult(
            summary_for_event="no summary",
            payload_for_model={"error": "summary_not_found"},
            citable_segments={},
        )
    summary, recording = row
    return ToolExecutionResult(
        summary_for_event=f"summary for {recording.title or 'untitled'}",
        payload_for_model={
            "recording_title": recording.title,
            "summary": summary.summary,
            "key_points": summary.key_points,
            "decisions": summary.decisions,
            "topics": summary.topics,
            "people_mentioned": summary.people_mentioned,
            "sentiment": summary.sentiment,
        },
        citable_segments={},
    )


async def _tool_list_recordings(
    db: AsyncSession, user_id: uuid.UUID, args: dict[str, Any]
) -> ToolExecutionResult:
    limit = args.get("limit", 25)
    stmt = (
        select(Recording)
        .where(
            and_(
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
        .order_by(Recording.created_at.desc())
        .limit(limit)
    )
    if args.get("date_from"):
        stmt = stmt.where(
            Recording.created_at >= datetime.fromisoformat(args["date_from"])
        )
    if args.get("date_to"):
        stmt = stmt.where(
            Recording.created_at <= datetime.fromisoformat(args["date_to"])
        )

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return ToolExecutionResult(
        summary_for_event=f"{len(rows)} recordings",
        payload_for_model={
            "recordings": [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "type": r.type,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "duration_seconds": r.duration_seconds,
                }
                for r in rows
            ]
        },
        citable_segments={},
    )


async def _execute_tool(
    name: str,
    args: dict[str, Any],
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    if name == "search_transcripts":
        return await _tool_search_transcripts(db, user_id, args, scope)
    if name == "get_recording_summary":
        return await _tool_get_recording_summary(db, user_id, args)
    if name == "list_recordings":
        return await _tool_list_recordings(db, user_id, args)
    raise CompanionError("unknown_tool", f"Unknown tool: {name}")


# ---------- The main turn loop ----------


@dataclass
class _CompletedTurn:
    assistant_content: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    markdown: str
    citations: list[dict[str, Any]]
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    latency_ms: int
    model: str


async def _load_history(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_WINDOW)
    )
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    return messages


def _history_to_responses_input(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Convert persisted messages to the OpenAI Responses input format."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            text = m.content if isinstance(m.content, str) else json.dumps(m.content)
            out.append({"role": "user", "content": text})
        elif m.role == "assistant":
            text = m.content if isinstance(m.content, str) else json.dumps(m.content)
            out.append({"role": "assistant", "content": text})
        # 'tool' role messages from old turns are not replayed; only their
        # final assistant text matters for downstream context.
    return out


async def run_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_text: str,
    *,
    openai_client=None,
) -> AsyncIterator[CompanionEvent]:
    """Execute one turn end-to-end, persisting messages and yielding events.

    `openai_client` may be injected for testing; otherwise the singleton is used.
    """
    settings = get_settings()
    client = openai_client if openai_client is not None else get_openai_client()
    started = time.monotonic()

    conv = await _load_conversation(db, user_id, conversation_id)

    user_msg = ChatMessage(
        conversation_id=conv.id,
        role="user",
        content=user_text,
    )
    db.add(user_msg)
    await db.flush()
    await db.refresh(user_msg)

    yield TurnStartEvent(
        message_id=str(user_msg.id),
        conversation_id=str(conv.id),
    )

    # Phase A — agentic tool loop.
    history = await _load_history(db, conv.id)
    base_input = _history_to_responses_input(history)
    tool_definitions_payload = tool_definitions()
    citable_allowlist: dict[str, SourceSegment] = {}
    raw_tool_calls: list[dict[str, Any]] = []

    a_input = list(base_input)
    tool_calls_made = 0
    response = None

    while True:
        if tool_calls_made >= TOOL_CALL_CAP:
            break

        response = await client.responses.create(
            model=settings.openai_llm_model,
            instructions=SYSTEM_PROMPT,
            input=a_input,
            tools=tool_definitions_payload,
            parallel_tool_calls=False,
            prompt_cache_key=f"wai-companion-{user_id}",
        )

        tool_calls = _extract_tool_calls(response)
        if not tool_calls:
            break

        for call in tool_calls:
            if tool_calls_made >= TOOL_CALL_CAP:
                break
            tool_calls_made += 1
            raw_tool_calls.append(
                {
                    "id": call["id"],
                    "name": call["name"],
                    "arguments": call["arguments"],
                }
            )
            yield ToolCallEvent(
                call_id=call["id"], tool=call["name"], args=call["arguments"]
            )
            result = await _execute_tool(
                call["name"], call["arguments"], db, user_id, conv.scope
            )
            citable_allowlist.update(result.citable_segments)
            yield ToolResultEvent(
                call_id=call["id"], summary=result.summary_for_event
            )
            a_input.append(
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"]),
                }
            )
            a_input.append(
                {
                    "type": "function_call_output",
                    "call_id": call["id"],
                    "output": json.dumps(result.payload_for_model),
                }
            )

    # Phase B — structured synthesis with response_format.
    allowlist_note = (
        "Allowed citation segment_ids (others will be rejected): "
        + ", ".join(sorted(citable_allowlist.keys()))
        if citable_allowlist
        else "No citable segments — answer that you found nothing."
    )
    b_input = a_input + [
        {
            "role": "user",
            "content": (
                "Now write the final answer for the user. "
                "Use inline [1] [2] markers and emit citations only for "
                "segment_ids from the search results above. "
                f"{allowlist_note}"
            ),
        }
    ]

    b_response = await client.responses.create(
        model=settings.openai_llm_model,
        instructions=SYSTEM_PROMPT,
        input=b_input,
        text={
            "format": {
                "type": "json_schema",
                **final_answer_schema(),
            }
        },
        prompt_cache_key=f"wai-companion-{user_id}",
    )
    final_text = _extract_text(b_response)
    try:
        parsed = json.loads(final_text)
    except json.JSONDecodeError as exc:
        raise CompanionError(
            "invalid_structured_output",
            f"Model returned non-JSON final answer: {exc}",
        ) from exc

    markdown = parsed["markdown"]
    raw_citations = parsed["citations"]
    valid_citations: list[dict[str, Any]] = []
    dropped = 0
    for cit in raw_citations:
        seg = citable_allowlist.get(cit["segment_id"])
        if seg is None:
            dropped += 1
            continue
        valid_citations.append(
            {
                "index": cit["index"],
                "segment_id": seg.segment_id,
                "recording_id": seg.recording_id,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "span_start": cit["span_start"],
                "span_end": cit["span_end"],
            }
        )

    # Stream the markdown to the caller as token events. (Real OpenAI streaming
    # would emit deltas mid-call; with the create() pattern we emit the final
    # text as a single token so the SSE wire shape is unchanged.)
    yield TokenEvent(text=markdown)
    for cit in valid_citations:
        yield CitationEvent(
            index=cit["index"],
            segment_id=cit["segment_id"],
            recording_id=cit["recording_id"],
            start_ms=cit["start_ms"],
            end_ms=cit["end_ms"],
            span_start=cit["span_start"],
            span_end=cit["span_end"],
        )

    # Combine Phase-A + Phase-B usage.
    a_usage = getattr(response, "usage", None) if response is not None else None
    b_usage = getattr(b_response, "usage", None)
    input_tokens = (_get_usage(a_usage, "input_tokens")) + _get_usage(
        b_usage, "input_tokens"
    )
    output_tokens = _get_usage(a_usage, "output_tokens") + _get_usage(
        b_usage, "output_tokens"
    )
    cached_tokens = _get_usage(a_usage, "cached_tokens") + _get_usage(
        b_usage, "cached_tokens"
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    assistant_content = [{"type": "text", "text": markdown}]
    assistant_msg = ChatMessage(
        conversation_id=conv.id,
        role="assistant",
        content=assistant_content,
        tool_calls=raw_tool_calls or None,
        cached_tokens=cached_tokens or None,
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        model=settings.openai_llm_model,
        latency_ms=latency_ms,
    )
    db.add(assistant_msg)
    await db.flush()
    await db.refresh(assistant_msg)

    for cit in valid_citations:
        db.add(
            MessageCitation(
                message_id=assistant_msg.id,
                segment_id=uuid.UUID(cit["segment_id"]),
                recording_id=uuid.UUID(cit["recording_id"]),
                span_start=cit["span_start"],
                span_end=cit["span_end"],
                citation_index=cit["index"],
            )
        )

    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()

    if dropped:
        logger.warning(
            "companion citation_drop_count=%d conversation_id=%s",
            dropped,
            conv.id,
        )

    yield DoneEvent(
        message_id=str(assistant_msg.id),
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        cached_tokens=cached_tokens or None,
        model=settings.openai_llm_model,
        latency_ms=latency_ms,
    )


async def _load_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            and_(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conv


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    """Pull function_call items out of the Responses API output."""
    output = getattr(response, "output", None) or []
    calls: list[dict[str, Any]] = []
    for item in output:
        item_type = getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )
        if item_type != "function_call":
            continue
        if isinstance(item, dict):
            raw_args = item.get("arguments") or "{}"
            calls.append(
                {
                    "id": item.get("call_id") or item.get("id"),
                    "name": item.get("name"),
                    "arguments": json.loads(raw_args),
                }
            )
        else:
            raw_args = getattr(item, "arguments", None) or "{}"
            calls.append(
                {
                    "id": getattr(item, "call_id", None) or getattr(item, "id", None),
                    "name": getattr(item, "name", None),
                    "arguments": json.loads(raw_args),
                }
            )
    return calls


def _extract_text(response: Any) -> str:
    """Pull the assistant text from a Responses API response."""
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    output = getattr(response, "output", None) or []
    parts: list[str] = []
    for item in output:
        if isinstance(item, dict):
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
        else:
            for c in getattr(item, "content", None) or []:
                if getattr(c, "type", None) == "output_text":
                    parts.append(getattr(c, "text", ""))
    return "".join(parts)


def _get_usage(usage: Any, field_name: str) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(field_name) or 0)
    raw = getattr(usage, field_name, None)
    if raw is None and field_name == "cached_tokens":
        details = getattr(usage, "input_tokens_details", None)
        if details is not None:
            raw = (
                details.get("cached_tokens")
                if isinstance(details, dict)
                else getattr(details, "cached_tokens", None)
            )
    return int(raw or 0)
