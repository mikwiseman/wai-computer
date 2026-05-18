"""Wai Companion service: agentic tool loop + streaming structured synthesis.

Phase A: the model is given `search_transcripts`, `get_recording_summary`,
and `list_recordings` tools. It drives retrieval freely (up to TOOL_CALL_CAP
calls) and then emits a text-only response signalling the search is done.

Phase B: a single streaming Responses API call with `response_format` set to
a strict JSON schema asks the model to write the final answer plus citations.
The server emits markdown deltas as `TokenEvent`s, validates every citation's
`segment_id` against the allowlist (the union of segment_ids returned by every
`search_transcripts` call in Phase A) and drops any that don't match — no
retry, no fallback.
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
                    "query": {"type": "string", "minLength": 1},
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


def _scope_recording_uuids(scope: dict[str, Any] | None) -> list[uuid.UUID] | None:
    if not scope:
        return None
    raw = scope.get("recording_ids")
    if not raw:
        return None
    try:
        return [uuid.UUID(r) for r in raw]
    except (TypeError, ValueError) as exc:
        raise CompanionError(
            "invalid_scope",
            f"Conversation scope has malformed recording_ids: {exc}",
        ) from exc


def _intersect_recording_ids(
    explicit: list[uuid.UUID] | None,
    scope: list[uuid.UUID] | None,
) -> list[uuid.UUID] | None:
    if scope is None:
        return explicit
    if explicit is None:
        return scope
    scope_set = set(scope)
    return [r for r in explicit if r in scope_set]


async def _tool_search_transcripts(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise CompanionError(
            "invalid_tool_args", "search_transcripts.query must be non-empty"
        )
    k = args.get("k", 15)
    explicit_raw = args.get("recording_ids")
    explicit: list[uuid.UUID] | None = None
    if explicit_raw:
        try:
            explicit = [uuid.UUID(r) for r in explicit_raw]
        except (TypeError, ValueError) as exc:
            raise CompanionError(
                "invalid_tool_args",
                f"search_transcripts.recording_ids has malformed id: {exc}",
            ) from exc

    scope_ids = _scope_recording_uuids(scope)
    recording_ids = _intersect_recording_ids(explicit, scope_ids)

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
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    raw = args.get("recording_id")
    try:
        recording_id = uuid.UUID(raw)
    except (TypeError, ValueError) as exc:
        raise CompanionError(
            "invalid_tool_args",
            f"get_recording_summary.recording_id is missing or malformed: {exc}",
        ) from exc

    scope_ids = _scope_recording_uuids(scope)
    if scope_ids is not None and recording_id not in scope_ids:
        return ToolExecutionResult(
            summary_for_event="out of scope",
            payload_for_model={
                "ok": False,
                "reason": "out_of_scope",
                "detail": "The requested recording is not part of this chat's scope.",
            },
            citable_segments={},
        )

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
            payload_for_model={
                "ok": False,
                "reason": "summary_not_found",
                "detail": "No summary exists for that recording yet.",
            },
            citable_segments={},
        )
    summary, recording = row
    return ToolExecutionResult(
        summary_for_event=f"summary for {recording.title or 'untitled'}",
        payload_for_model={
            "ok": True,
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
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
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
        try:
            stmt = stmt.where(
                Recording.created_at >= datetime.fromisoformat(args["date_from"])
            )
        except (TypeError, ValueError) as exc:
            raise CompanionError(
                "invalid_tool_args",
                f"list_recordings.date_from is not ISO-8601: {exc}",
            ) from exc
    if args.get("date_to"):
        try:
            stmt = stmt.where(
                Recording.created_at <= datetime.fromisoformat(args["date_to"])
            )
        except (TypeError, ValueError) as exc:
            raise CompanionError(
                "invalid_tool_args",
                f"list_recordings.date_to is not ISO-8601: {exc}",
            ) from exc

    scope_ids = _scope_recording_uuids(scope)
    if scope_ids is not None:
        stmt = stmt.where(Recording.id.in_(scope_ids))

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


_TOOL_DISPATCH = {
    "search_transcripts": _tool_search_transcripts,
    "get_recording_summary": _tool_get_recording_summary,
    "list_recordings": _tool_list_recordings,
}


async def _execute_tool(
    name: str,
    args: dict[str, Any],
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        raise CompanionError("unknown_tool", f"Unknown tool: {name}")
    return await handler(db, user_id, args, scope)


# ---------- Streaming JSON markdown extractor ----------


class _MarkdownDeltaExtractor:
    """Extract the value of the JSON field `markdown` as it streams in.

    The Phase-B model output is a strict JSON object of the form
    `{"markdown": "...", "citations": [...]}`. While streaming we only want to
    surface the markdown value to the client. This is a minimal state machine
    that scans the incremental buffer, decodes the value's escape sequences,
    and returns whatever new characters have become certain so far.
    """

    _STATE_BEFORE = 0
    _STATE_INSIDE = 1
    _STATE_DONE = 2

    def __init__(self) -> None:
        self._buffer = ""
        self._state = self._STATE_BEFORE
        self._scan_pos = 0

    @property
    def is_done(self) -> bool:
        return self._state == self._STATE_DONE

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self._buffer += delta
        if self._state == self._STATE_DONE:
            return ""
        if self._state == self._STATE_BEFORE:
            if not self._locate_markdown_value():
                return ""
        return self._consume_string()

    def _locate_markdown_value(self) -> bool:
        idx = self._buffer.find('"markdown"')
        if idx < 0:
            return False
        i = idx + len('"markdown"')
        while i < len(self._buffer) and self._buffer[i] in " \t\n\r":
            i += 1
        if i >= len(self._buffer) or self._buffer[i] != ":":
            return False
        i += 1
        while i < len(self._buffer) and self._buffer[i] in " \t\n\r":
            i += 1
        if i >= len(self._buffer) or self._buffer[i] != '"':
            return False
        self._scan_pos = i + 1
        self._state = self._STATE_INSIDE
        return True

    def _consume_string(self) -> str:
        buf = self._buffer
        out: list[str] = []
        i = self._scan_pos
        n = len(buf)
        while i < n:
            c = buf[i]
            if c == "\\":
                if i + 1 >= n:
                    break
                nc = buf[i + 1]
                if nc == "u":
                    if i + 5 >= n:
                        break
                    hex_str = buf[i + 2 : i + 6]
                    try:
                        out.append(chr(int(hex_str, 16)))
                    except ValueError:
                        out.append(buf[i : i + 6])
                    i += 6
                    continue
                simple = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "b": "\b",
                    "f": "\f",
                }.get(nc)
                if simple is None:
                    out.append(buf[i : i + 2])
                else:
                    out.append(simple)
                i += 2
            elif c == '"':
                self._state = self._STATE_DONE
                self._scan_pos = i + 1
                return "".join(out)
            else:
                out.append(c)
                i += 1
        self._scan_pos = i
        return "".join(out)


# ---------- The main turn loop ----------


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
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            text = m.content if isinstance(m.content, str) else json.dumps(m.content)
            out.append({"role": "user", "content": text})
        elif m.role == "assistant":
            text = m.content if isinstance(m.content, str) else json.dumps(m.content)
            out.append({"role": "assistant", "content": text})
    return out


async def run_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_text: str,
    *,
    openai_client=None,
) -> AsyncIterator[CompanionEvent]:
    settings = get_settings()
    client = openai_client if openai_client is not None else get_openai_client()
    started = time.monotonic()

    conv = await _load_conversation_locked(db, user_id, conversation_id)

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

    # Phase B — streaming structured synthesis.
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

    extractor = _MarkdownDeltaExtractor()
    raw_b_text = ""
    b_usage: Any = None

    stream = await client.responses.create(
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
        stream=True,
    )

    async for event in stream:
        event_type = getattr(event, "type", None) or (
            event.get("type") if isinstance(event, dict) else None
        )
        if event_type == "response.output_text.delta":
            delta = getattr(event, "delta", None)
            if delta is None and isinstance(event, dict):
                delta = event.get("delta", "")
            delta = delta or ""
            raw_b_text += delta
            new_md = extractor.feed(delta)
            if new_md:
                yield TokenEvent(text=new_md)
        elif event_type in ("response.completed", "response.done"):
            response_obj = getattr(event, "response", None)
            if response_obj is None and isinstance(event, dict):
                response_obj = event.get("response")
            if response_obj is not None:
                b_usage = getattr(response_obj, "usage", None)
                if b_usage is None and isinstance(response_obj, dict):
                    b_usage = response_obj.get("usage")
                if not raw_b_text:
                    raw_b_text = _extract_text(response_obj)
        elif event_type == "response.error" or event_type == "error":
            err = getattr(event, "error", None)
            if err is None and isinstance(event, dict):
                err = event.get("error")
            err_msg = (
                getattr(err, "message", None)
                or (err.get("message") if isinstance(err, dict) else None)
                or "Phase-B stream failed"
            )
            raise CompanionError("phase_b_stream_error", str(err_msg))

    if not raw_b_text:
        raise CompanionError(
            "invalid_structured_output",
            "Phase-B stream completed without emitting any output text.",
        )

    try:
        parsed = json.loads(raw_b_text)
    except json.JSONDecodeError as exc:
        raise CompanionError(
            "invalid_structured_output",
            f"Model returned non-JSON final answer: {exc}",
        ) from exc

    try:
        markdown = parsed["markdown"]
        raw_citations = parsed["citations"]
    except (KeyError, TypeError) as exc:
        raise CompanionError(
            "invalid_structured_output",
            f"Phase-B JSON missing required fields: {exc}",
        ) from exc

    valid_citations: list[dict[str, Any]] = []
    dropped = 0
    for cit in raw_citations:
        seg = citable_allowlist.get(cit.get("segment_id", ""))
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

    a_usage = getattr(response, "usage", None) if response is not None else None
    input_tokens = _get_usage(a_usage, "input_tokens") + _get_usage(
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


async def _load_conversation_locked(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    """Load the conversation row, locking it on Postgres so concurrent turns serialize."""
    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
    stmt = select(Conversation).where(
        and_(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if dialect_name == "postgresql":
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conv


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
    output = output or []
    calls: list[dict[str, Any]] = []
    for item in output:
        item_type = getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )
        if item_type != "function_call":
            continue
        if isinstance(item, dict):
            raw_args = item.get("arguments") or "{}"
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise CompanionError(
                    "invalid_tool_args",
                    f"Tool call arguments are not valid JSON: {exc}",
                ) from exc
            calls.append(
                {
                    "id": item.get("call_id") or item.get("id"),
                    "name": item.get("name"),
                    "arguments": parsed_args,
                }
            )
        else:
            raw_args = getattr(item, "arguments", None) or "{}"
            try:
                parsed_args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise CompanionError(
                    "invalid_tool_args",
                    f"Tool call arguments are not valid JSON: {exc}",
                ) from exc
            calls.append(
                {
                    "id": getattr(item, "call_id", None) or getattr(item, "id", None),
                    "name": getattr(item, "name", None),
                    "arguments": parsed_args,
                }
            )
    return calls


def _extract_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text is None and isinstance(response, dict):
        output_text = response.get("output_text")
    if output_text:
        return output_text
    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
    output = output or []
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
        raw = usage.get(field_name)
        if raw is None and field_name == "cached_tokens":
            details = usage.get("input_tokens_details")
            if isinstance(details, dict):
                raw = details.get("cached_tokens")
        return int(raw) if raw is not None else 0
    raw = getattr(usage, field_name, None)
    if raw is None and field_name == "cached_tokens":
        details = getattr(usage, "input_tokens_details", None)
        if details is not None:
            raw = (
                details.get("cached_tokens")
                if isinstance(details, dict)
                else getattr(details, "cached_tokens", None)
            )
    return int(raw) if raw is not None else 0
