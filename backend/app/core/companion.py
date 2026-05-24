"""Wai Companion service: one streaming Responses call with Wai MCP attached."""

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
from app.core import user_memory as user_memory_module
from app.core.mcp_oauth import issue_companion_mcp_access_token
from app.core.openai_client import get_openai_client
from app.core.openai_responses import OpenAIResponseError, ensure_response_completed
from app.core.qa import SourceSegment, retrieve_context
from app.models.companion import ChatMessage, Conversation
from app.models.recording import ActionItem, Folder, Recording, Summary
from app.models.user import User
from app.models.user_memory import UserMemoryBlock

logger = logging.getLogger(__name__)

COMPANION_AUTO_TITLE_MAX_CHARS = 72

TOOL_CALL_CAP = 6
HISTORY_WINDOW = 20
SNIPPET_CHAR_CAP = 400

_IDENTITY_SECTION = (
    "<identity>\n"
    "You are Wai — a calm, precise partner. Not an assistant, not a "
    "chatbot. You answer over the user's recorded conversations, notes, "
    "and reflections.\n"
    "</identity>"
)

_TOOL_GUIDANCE_SECTION = (
    "<tool_guidance>\n"
    "Use the WaiComputer MCP server whenever the user asks about their "
    "recordings, folders, transcript content, summaries, decisions, or "
    "action items. Treat MCP as the only source of truth for library data.\n"
    "- search — use for content questions and specific topics.\n"
    "- fetch — use after search/list_recordings when one recording needs "
    "closer reading.\n"
    "- list_recordings — use for browsing, latest recordings, folder/date "
    "questions, and relative time questions.\n"
    "- list_folders — use before folder-scoped browse/search.\n"
    "- list_action_items — use for commitments, TODOs, promises, and "
    "follow-ups.\n"
    "If MCP returns no relevant data, say that directly. Do not invent facts "
    "or mention internal tool mechanics.\n"
    "</tool_guidance>"
)

_ANSWER_FORMAT_SECTION = (
    "<answer_format>\n"
    "- Match the language of the user's most recent message. If they "
    "wrote in Russian, answer in Russian.\n"
    "- One paragraph default. Bullets only when the answer is a list.\n"
    "- Do not start with 'Sure!', 'I'd be happy to', or any "
    "acknowledgement. Do not narrate your reasoning or say 'based on the "
    "transcripts'. Do not use emojis unless the user does first.\n"
    "- When the corpus is silent, say so in one sentence and stop.\n"
    "</answer_format>"
)


def _render_user_profile(user: User | None) -> str:
    """Compact <user_profile> block. Empty when there's no user (tests)."""
    if user is None:
        return ""
    lines: list[str] = ["<user_profile>"]
    lines.append(f"default_language: {user.default_language}")
    lines.append(f"summary_language: {user.summary_language}")
    lines.append(f"summary_style: {user.summary_style}")
    if user.summary_instructions:
        lines.append(
            f"summary_instructions: {user.summary_instructions.strip()[:240]}"
        )
    lines.append("</user_profile>")
    return "\n".join(lines)


def _render_memory_section(memory_strings: dict[str, str] | None) -> str:
    """Render a <memory> section from a plain {label: body-string} dict.

    Used internally by `system_prompt_for` when the caller has already
    serialised blocks; mirrors `user_memory.render_for_prompt` but takes
    strings instead of ORM rows. Kept on this module for callers (tests,
    consolidator pre-renders) that have nothing but strings on hand.
    """
    if not memory_strings:
        return ""
    sections: list[str] = []
    for label, body in memory_strings.items():
        body = (body or "").strip()
        if not body:
            continue
        sections.append(f"## {label}\n{body}")
    if not sections:
        return ""
    return "<memory>\n" + "\n\n".join(sections) + "\n</memory>"


def system_prompt_for(
    user: User | None = None,
    memory_blocks: dict[str, UserMemoryBlock] | dict[str, str] | None = None,
) -> str:
    """Assemble the cacheable system prompt for a turn.

    Order: identity → user_profile → memory → tool_guidance → answer_format.
    The first three sections vary per user but rarely; the last two are
    fully static. With `prompt_cache_key` keyed to user_id this keeps a
    stable prefix that's well above the 1024-token cache warm threshold
    once user_profile and memory accumulate.
    """
    sections: list[str] = [_IDENTITY_SECTION]
    profile = _render_user_profile(user)
    if profile:
        sections.append(profile)
    if memory_blocks:
        first = next(iter(memory_blocks.values()))
        if isinstance(first, str):
            memory = _render_memory_section(memory_blocks)  # type: ignore[arg-type]
        else:
            memory = user_memory_module.render_for_prompt(memory_blocks)
        if memory:
            sections.append(memory)
    sections.append(_TOOL_GUIDANCE_SECTION)
    sections.append(_ANSWER_FORMAT_SECTION)
    return "\n\n".join(sections)


# Back-compat for any caller still importing SYSTEM_PROMPT directly. New code
# should call `system_prompt_for(user, memory_blocks)` so per-user profile +
# memory blocks land in the cacheable prefix.
SYSTEM_PROMPT = system_prompt_for()


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


@dataclass(frozen=True)
class MemoryUpdatedEvent:
    """Emitted whenever the `remember` tool successfully writes to a memory
    block, so the client can surface a subtle "Wai remembered X" toast.
    Parallel to ToolCallEvent — clients that don't know about it ignore it."""

    type: Literal["memory_updated"] = "memory_updated"
    block: str = ""
    operation: str = ""


CompanionEvent = (
    TurnStartEvent
    | ToolCallEvent
    | ToolResultEvent
    | TokenEvent
    | CitationEvent
    | MemoryUpdatedEvent
    | DoneEvent
    | ErrorEvent
)


class CompanionError(Exception):
    """Raised when a turn cannot complete (model error, validator rejection)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TurnContext:
    """Per-turn working memory the client supplies and the server forwards
    verbatim to the model as a developer message.

    Kept out of the cacheable `instructions` prefix on purpose: the date and
    viewing fields change every turn, and including them in `instructions`
    would invalidate the prompt cache on every request.
    """

    client_local_date: str | None = None      # ISO "2026-05-18"
    client_timezone: str | None = None        # IANA, e.g. "Europe/Reykjavik"
    viewing_recording_title: str | None = None
    viewing_folder_name: str | None = None


# ---------- Tool definitions advertised to the model ----------


def tool_definitions() -> list[dict[str, Any]]:
    """OpenAI Responses-API tool schemas. Descriptions follow the Anthropic
    "right altitude" pattern: when to use, when NOT to use, output shape.
    They are duplicated in compact form inside <tool_guidance> in the
    cacheable system prefix; the long-form here lives next to the schema.
    """
    return [
        {
            "type": "function",
            "name": "search_transcripts",
            "description": (
                "Search verbatim transcript content. The ONLY tool that "
                "returns citable segment_ids — you may ONLY emit citations "
                "for segment_ids returned by this call. Use AFTER you "
                "know which recording(s) to search (from list_recordings, "
                "search_people, or the user naming one). Do NOT use this "
                "for date-range or person-name lookups — that's "
                "list_recordings / search_people. Returns 1-30 segments "
                "with snippet, speaker, start_ms, end_ms."
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
                "Dense pre-extracted view of ONE recording: summary, key "
                "points, decisions, topics, people mentioned, sentiment. "
                "Use after list_recordings narrowed things down and you "
                "want context on a single recording before quoting it. "
                "Output is NOT citable — call search_transcripts on the "
                "same recording_id for citations."
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
                "Navigation tool — call FIRST when the user uses any "
                "relative time word (today, yesterday, last week, this "
                "morning, вчера, сегодня, на прошлой неделе) or asks "
                "about a recording they did not name. Pass date_from / "
                "date_to in the user's local timezone (see <session> in "
                "the developer message above). Returns title + type + "
                "folder + one-line summary + topics per recording so you "
                "can pick the right one without a second call. Context-"
                "only — NOT citable. Cap 50."
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
        {
            "type": "function",
            "name": "get_action_items",
            "description": (
                "List the user's commitments / TODOs extracted from "
                "recordings. Use when the user asks 'what do I owe', "
                "'what's on my plate', 'что я должен', 'мои задачи'. "
                "Filter by status (default pending), priority, owner, or "
                "due_before. NOT citable."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_progress",
                            "completed",
                            "cancelled",
                        ],
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "owner": {"type": "string"},
                    "due_before": {"type": "string", "format": "date"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
        },
        {
            "type": "function",
            "name": "get_highlights",
            "description": (
                "Key moments pre-extracted from recordings (decisions, "
                "insights, surprises). Use when the user asks 'what was "
                "important', 'key moments', 'что важного', 'highlights'. "
                "Filter by category, minimum importance (high|medium|low), "
                "and date range. NOT citable — drill into the underlying "
                "recording with search_transcripts if you want quotes."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string"},
                    "min_importance": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "date_from": {"type": "string", "format": "date-time"},
                    "date_to": {"type": "string", "format": "date-time"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
        },
        {
            "type": "function",
            "name": "search_people",
            "description": (
                "Find recordings featuring a person. Use when the user "
                "asks 'what did Alice say about X', 'когда я говорил с "
                "Mik', 'кто упоминал X'. Returns recordings only — "
                "follow up with search_transcripts(query=..., "
                "recording_ids=[...]) for citable quotes. NOT citable."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["name"],
            },
        },
        {
            "type": "function",
            "name": "remember",
            "description": (
                "Write a durable fact about the user to long-term memory. "
                "Use SPARINGLY — only when the fact is durable (preferences, "
                "relationships, ongoing projects, goals, where they live, "
                "what they're building, recurring topics). Do NOT use for "
                "single-conversation context, momentary tasks, or things "
                "the user can easily look up. The block 'human' holds "
                "facts about the user; 'topics' holds recurring "
                "subjects; 'preferences' holds answer-style notes. "
                "Operations: append (default), replace_line (needs "
                "target_line), rewrite (replaces the whole block). "
                "Server enforces a char_limit per block."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "block": {
                        "type": "string",
                        "enum": ["human", "topics", "preferences"],
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["append", "replace_line", "rewrite"],
                    },
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "target_line": {"type": "string"},
                },
                "required": ["block", "content"],
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


def _summary_one_line(summary: Summary | None) -> str | None:
    """First sentence of the recording's summary, capped — gives the
    model enough to pick the right recording without a follow-up tool
    call (Granola "navigate, don't lookup" pattern)."""
    if summary is None or not summary.summary:
        return None
    text = summary.summary.strip()
    # First sentence boundary; collapse trailing whitespace.
    for terminator in (". ", "! ", "? ", "\n"):
        idx = text.find(terminator)
        if idx != -1 and idx < 200:
            return text[: idx + 1].strip()
    return text[:200].rstrip()


async def _tool_list_recordings(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    limit = args.get("limit", 25)
    stmt = (
        select(Recording, Summary, Folder)
        .outerjoin(Summary, Summary.recording_id == Recording.id)
        .outerjoin(Folder, Folder.id == Recording.folder_id)
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
    rows = list(result.all())
    return ToolExecutionResult(
        summary_for_event=f"{len(rows)} recordings",
        payload_for_model={
            "recordings": [
                {
                    "id": str(rec.id),
                    "title": rec.title,
                    "type": rec.type,
                    "folder": folder.name if folder is not None else None,
                    "created_at": (
                        rec.created_at.isoformat() if rec.created_at else None
                    ),
                    "duration_seconds": rec.duration_seconds,
                    "summary_one_line": _summary_one_line(summary),
                    "topics": (summary.topics if summary is not None else None),
                }
                for (rec, summary, folder) in rows
            ]
        },
        citable_segments={},
    )


async def _tool_get_action_items(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    limit = args.get("limit", 25)
    stmt = (
        select(ActionItem, Recording)
        .join(Recording, ActionItem.recording_id == Recording.id)
        .where(
            and_(
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
        .order_by(
            ActionItem.due_date.asc().nulls_last(),
            ActionItem.created_at.desc(),
        )
        .limit(limit)
    )
    if args.get("status"):
        stmt = stmt.where(ActionItem.status == args["status"])
    else:
        # Default: only "pending" — users asking "what do I owe" almost
        # always mean open items, not done ones.
        stmt = stmt.where(ActionItem.status == "pending")
    if args.get("priority"):
        stmt = stmt.where(ActionItem.priority == args["priority"])
    if args.get("owner"):
        stmt = stmt.where(ActionItem.owner == args["owner"])
    if args.get("due_before"):
        try:
            from datetime import date as _date_cls

            due = _date_cls.fromisoformat(args["due_before"])
            stmt = stmt.where(ActionItem.due_date <= due)
        except (TypeError, ValueError) as exc:
            raise CompanionError(
                "invalid_tool_args",
                f"get_action_items.due_before is not ISO date: {exc}",
            ) from exc
    scope_ids = _scope_recording_uuids(scope)
    if scope_ids is not None:
        stmt = stmt.where(Recording.id.in_(scope_ids))

    result = await db.execute(stmt)
    rows = list(result.all())
    return ToolExecutionResult(
        summary_for_event=f"{len(rows)} action items",
        payload_for_model={
            "action_items": [
                {
                    "id": str(item.id),
                    "task": item.task,
                    "owner": item.owner,
                    "due_date": (
                        item.due_date.isoformat() if item.due_date else None
                    ),
                    "priority": item.priority,
                    "status": item.status,
                    "recording_id": str(rec.id),
                    "recording_title": rec.title,
                }
                for (item, rec) in rows
            ]
        },
        citable_segments={},
    )


_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


async def _tool_get_highlights(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    from app.models.highlight import Highlight

    limit = args.get("limit", 25)
    stmt = (
        select(Highlight, Recording)
        .join(Recording, Highlight.recording_id == Recording.id)
        .where(
            and_(
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
        .order_by(Recording.created_at.desc())
        .limit(limit)
    )
    if args.get("category"):
        stmt = stmt.where(Highlight.category == args["category"])
    if args.get("min_importance"):
        threshold = _IMPORTANCE_ORDER.get(args["min_importance"])
        if threshold is None:
            raise CompanionError(
                "invalid_tool_args",
                f"get_highlights.min_importance must be one of "
                f"{list(_IMPORTANCE_ORDER)}",
            )
        allowed = [
            level for level, rank in _IMPORTANCE_ORDER.items() if rank <= threshold
        ]
        stmt = stmt.where(Highlight.importance.in_(allowed))
    if args.get("date_from"):
        try:
            stmt = stmt.where(
                Recording.created_at >= datetime.fromisoformat(args["date_from"])
            )
        except (TypeError, ValueError) as exc:
            raise CompanionError(
                "invalid_tool_args",
                f"get_highlights.date_from is not ISO-8601: {exc}",
            ) from exc
    if args.get("date_to"):
        try:
            stmt = stmt.where(
                Recording.created_at <= datetime.fromisoformat(args["date_to"])
            )
        except (TypeError, ValueError) as exc:
            raise CompanionError(
                "invalid_tool_args",
                f"get_highlights.date_to is not ISO-8601: {exc}",
            ) from exc
    scope_ids = _scope_recording_uuids(scope)
    if scope_ids is not None:
        stmt = stmt.where(Recording.id.in_(scope_ids))

    result = await db.execute(stmt)
    rows = list(result.all())
    return ToolExecutionResult(
        summary_for_event=f"{len(rows)} highlights",
        payload_for_model={
            "highlights": [
                {
                    "id": str(h.id),
                    "category": h.category,
                    "title": h.title,
                    "description": h.description,
                    "speaker": h.speaker,
                    "importance": h.importance,
                    "start_ms": h.start_ms,
                    "end_ms": h.end_ms,
                    "recording_id": str(rec.id),
                    "recording_title": rec.title,
                    "recording_created_at": (
                        rec.created_at.isoformat() if rec.created_at else None
                    ),
                }
                for (h, rec) in rows
            ]
        },
        citable_segments={},
    )


async def _tool_search_people(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
) -> ToolExecutionResult:
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CompanionError(
            "invalid_tool_args", "search_people.name must be non-empty"
        )
    limit = args.get("limit", 10)

    from app.models.entity import Entity, EntityRelation

    # 1. Find person entities matching the requested name (case-insensitive).
    entity_stmt = select(Entity.id).where(
        and_(
            Entity.user_id == user_id,
            Entity.type == "person",
            Entity.name.ilike(f"%{name.strip()}%"),
        )
    )
    entity_ids = list((await db.execute(entity_stmt)).scalars().all())
    if not entity_ids:
        return ToolExecutionResult(
            summary_for_event="no people found",
            payload_for_model={"recordings": [], "matched_entities": []},
            citable_segments={},
        )

    # 2. Recordings linked to those entities via EntityRelation. There is no
    #    EntityMention table — the relation table is the only link.
    from sqlalchemy import or_ as sa_or

    rel_stmt = (
        select(EntityRelation.recording_id)
        .where(
            and_(
                EntityRelation.recording_id.is_not(None),
                sa_or(
                    EntityRelation.source_id.in_(entity_ids),
                    EntityRelation.target_id.in_(entity_ids),
                ),
            )
        )
        .distinct()
    )
    recording_ids = list(
        (await db.execute(rel_stmt)).scalars().all()
    )
    if not recording_ids:
        return ToolExecutionResult(
            summary_for_event="0 recordings",
            payload_for_model={
                "recordings": [],
                "matched_entities": [str(e) for e in entity_ids],
            },
            citable_segments={},
        )

    scope_ids = _scope_recording_uuids(scope)
    if scope_ids is not None:
        allowed = set(scope_ids)
        recording_ids = [r for r in recording_ids if r in allowed]

    rec_stmt = (
        select(Recording)
        .where(
            and_(
                Recording.id.in_(recording_ids),
                Recording.user_id == user_id,
                Recording.deleted_at.is_(None),
            )
        )
        .order_by(Recording.created_at.desc())
        .limit(limit)
    )
    recs = list((await db.execute(rec_stmt)).scalars().all())
    return ToolExecutionResult(
        summary_for_event=f"{len(recs)} recordings",
        payload_for_model={
            "recordings": [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "type": r.type,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
                for r in recs
            ],
            "matched_entities": [str(e) for e in entity_ids],
        },
        citable_segments={},
    )


async def _tool_remember(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: dict[str, Any],
    scope: dict[str, Any] | None,
    *,
    conversation_id: uuid.UUID | None = None,
) -> ToolExecutionResult:
    """Write a durable fact to long-term memory. Single source of truth
    for memory writes is app.core.user_memory.write_block — both this
    tool and the nightly consolidator go through it."""
    label = args.get("block")
    operation = args.get("operation", "append")
    content = args.get("content", "")
    target_line = args.get("target_line")

    try:
        result = await user_memory_module.write_block(
            db,
            user_id,
            label=label,
            operation=operation,
            content=content,
            target_line=target_line,
            source="agent",
            conversation_id=conversation_id,
        )
    except user_memory_module.MemoryError as exc:
        return ToolExecutionResult(
            summary_for_event="memory write rejected",
            payload_for_model={
                "ok": False,
                "reason": "memory_write_rejected",
                "detail": str(exc),
            },
            citable_segments={},
        )

    return ToolExecutionResult(
        summary_for_event=f"updated memory block: {label}",
        payload_for_model={
            "ok": True,
            "block": label,
            "operation": operation,
            "new_length_chars": len(result.after),
        },
        citable_segments={},
    )


_TOOL_DISPATCH = {
    "search_transcripts": _tool_search_transcripts,
    "get_recording_summary": _tool_get_recording_summary,
    "list_recordings": _tool_list_recordings,
    "get_action_items": _tool_get_action_items,
    "get_highlights": _tool_get_highlights,
    "search_people": _tool_search_people,
    "remember": _tool_remember,
}


async def _execute_tool(
    name: str,
    args: dict[str, Any],
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: dict[str, Any] | None,
    *,
    conversation_id: uuid.UUID | None = None,
) -> ToolExecutionResult:
    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        raise CompanionError("unknown_tool", f"Unknown tool: {name}")
    if name == "remember":
        return await handler(
            db, user_id, args, scope, conversation_id=conversation_id
        )
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
    cached_mcp_list_tools = _latest_mcp_list_tools_item(messages)
    if cached_mcp_list_tools is not None:
        out.append(cached_mcp_list_tools)

    for m in messages:
        if m.role == "user":
            text = _message_content_to_text(m.content)
            out.append({"role": "user", "content": text})
        elif m.role == "assistant":
            text = _message_content_to_text(m.content)
            out.append({"role": "assistant", "content": text})
    return out


def _latest_mcp_list_tools_item(messages: list[ChatMessage]) -> dict[str, Any] | None:
    for message in reversed(messages):
        tool_calls = getattr(message, "tool_calls", None)
        if message.role != "assistant" or not isinstance(tool_calls, list):
            continue
        for item in tool_calls:
            if isinstance(item, dict) and item.get("type") == "mcp_list_tools":
                return item
    return None


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return json.dumps(content)


def _format_weekday(iso_date: str) -> str:
    """Return ', Mon' / ', Sat' for the given ISO date, or '' if unparseable."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return ""
    return f", {d.strftime('%A')}"


def _format_scope_for_session(scope: dict[str, Any] | None) -> str:
    if not scope:
        return "all of the user's recordings"
    rec_ids = scope.get("recording_ids") if isinstance(scope, dict) else None
    if rec_ids:
        n = len(rec_ids)
        return f"{n} pinned recording{'s' if n != 1 else ''}"
    return "all of the user's recordings"


def _build_session_developer_message(
    ctx: TurnContext | None,
    scope: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Render the per-turn developer message describing date / tz / scope /
    what the user is currently viewing. Goes in `input` (not `instructions`)
    so the cacheable prefix is stable across turns.

    Returns None when there is genuinely nothing to say (ctx is None and
    scope is empty) — keeps short test fixtures clean.
    """
    if ctx is None and not scope:
        return None
    ctx = ctx or TurnContext()
    lines: list[str] = ["<session>"]
    if ctx.client_local_date:
        weekday = _format_weekday(ctx.client_local_date)
        lines.append(f"date: {ctx.client_local_date}{weekday}")
    else:
        lines.append(
            "date: unknown (client did not send a local date — do not "
            "guess; if the user uses a relative time word, ask)"
        )
    if ctx.client_timezone:
        lines.append(f"timezone: {ctx.client_timezone}")
    else:
        lines.append(
            "timezone: unknown (client did not send one — assume the "
            "user's date above already covers their local day)"
        )
    lines.append(f"scope: {_format_scope_for_session(scope)}")
    if ctx.viewing_recording_title:
        lines.append(
            f"user is currently viewing recording: "
            f"{ctx.viewing_recording_title}"
        )
    if ctx.viewing_folder_name:
        lines.append(
            f"user is currently viewing folder: {ctx.viewing_folder_name}"
        )
    lines.append("</session>")
    return {"role": "developer", "content": "\n".join(lines)}


def _companion_mcp_tool(settings, access_token: str) -> dict[str, Any]:
    return {
        "type": "mcp",
        "server_label": "wai",
        "server_url": settings.mcp_resource_url_resolved,
        "authorization": access_token,
        "require_approval": "never",
        "allowed_tools": [
            "search",
            "fetch",
            "list_folders",
            "list_recordings",
            "list_action_items",
        ],
    }


async def run_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_text: str,
    *,
    turn_context: TurnContext | None = None,
    openai_client=None,
) -> AsyncIterator[CompanionEvent]:
    settings = get_settings()
    client = openai_client if openai_client is not None else get_openai_client()
    started = time.monotonic()

    conv = await _load_conversation_locked(db, user_id, conversation_id)
    user_row = await db.get(User, user_id)
    memory_blocks = await user_memory_module.get_or_seed_blocks(db, user_id)
    instructions = system_prompt_for(user_row, memory_blocks=memory_blocks)

    if not (conv.title or "").strip() and not await _conversation_has_messages(
        db, conv.id
    ):
        conv.title = _auto_title_from_user_request(user_text)

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
    session_message = _build_session_developer_message(
        turn_context, conv.scope
    )
    response_input: list[dict[str, Any]] = []
    if session_message is not None:
        response_input.append(session_message)
    response_input.extend(base_input)

    access_token = await issue_companion_mcp_access_token(db, user_id)
    # OpenAI calls the remote MCP server from outside this DB transaction.
    # Commit the just-issued token (and the user turn) before the stream starts
    # so `/mcp` can resolve the presented token on its own connection.
    await db.commit()
    mcp_tool = _companion_mcp_tool(settings, access_token)

    assistant_text = ""
    usage: Any = None
    completed_response_obj: Any = None
    stream = await client.responses.create(
        model=settings.openai_llm_model,
        instructions=instructions,
        input=response_input,
        tools=[mcp_tool],
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
            assistant_text += delta
            if delta:
                yield TokenEvent(text=delta)
        elif event_type in ("response.completed", "response.done"):
            response_obj = getattr(event, "response", None)
            if response_obj is None and isinstance(event, dict):
                response_obj = event.get("response")
            if response_obj is not None:
                completed_response_obj = response_obj
                try:
                    ensure_response_completed(response_obj, operation="Companion response")
                except OpenAIResponseError as exc:
                    raise CompanionError("model_incomplete", str(exc)) from exc
                usage = getattr(response_obj, "usage", None)
                if usage is None and isinstance(response_obj, dict):
                    usage = response_obj.get("usage")
                if not assistant_text:
                    assistant_text = _extract_text(response_obj)
                    if assistant_text:
                        yield TokenEvent(text=assistant_text)
        elif event_type == "response.error" or event_type == "error":
            err = getattr(event, "error", None)
            if err is None and isinstance(event, dict):
                err = event.get("error")
            err_msg = (
                getattr(err, "message", None)
                or (err.get("message") if isinstance(err, dict) else None)
                or "Companion stream failed"
            )
            raise CompanionError("stream_error", str(err_msg))

    assistant_text = assistant_text.strip()
    if not assistant_text:
        raise CompanionError(
            "empty_model_output",
            "Companion stream completed without emitting any text.",
        )

    input_tokens = _get_usage(usage, "input_tokens")
    output_tokens = _get_usage(usage, "output_tokens")
    cached_tokens = _get_usage(usage, "cached_tokens")
    latency_ms = int((time.monotonic() - started) * 1000)

    assistant_content = [{"type": "text", "text": assistant_text}]
    mcp_context_items = _extract_mcp_context_items(completed_response_obj)
    assistant_msg = ChatMessage(
        conversation_id=conv.id,
        role="assistant",
        content=assistant_content,
        tool_calls=mcp_context_items or None,
        cached_tokens=cached_tokens or None,
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        model=settings.openai_llm_model,
        latency_ms=latency_ms,
    )
    db.add(assistant_msg)
    await db.flush()
    await db.refresh(assistant_msg)

    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()

    yield DoneEvent(
        message_id=str(assistant_msg.id),
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        cached_tokens=cached_tokens or None,
        model=settings.openai_llm_model,
        latency_ms=latency_ms,
    )


async def _conversation_has_messages(db: AsyncSession, conversation_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def _auto_title_from_user_request(user_text: str) -> str:
    title = " ".join(user_text.split())
    if len(title) <= COMPANION_AUTO_TITLE_MAX_CHARS:
        return title
    return title[: COMPANION_AUTO_TITLE_MAX_CHARS - 3].rstrip() + "..."


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


def _extract_mcp_context_items(response_obj: Any) -> list[dict[str, Any]]:
    output = getattr(response_obj, "output", None)
    if output is None and isinstance(response_obj, dict):
        output = response_obj.get("output")
    output = output or []
    items: list[dict[str, Any]] = []
    for item in output:
        data = _response_item_to_dict(item)
        if data.get("type") == "mcp_list_tools":
            items.append(data)
    return items


def _response_item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    data: dict[str, Any] = {}
    for key in ("id", "type", "server_label", "tools"):
        value = getattr(item, key, None)
        if value is not None:
            data[key] = value
    return data


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
