"""Wai Companion service: one streaming Responses call with Wai MCP attached."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Literal
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import brain_spaces as brain_space_service
from app.core import user_memory as user_memory_module
from app.core.companion_actions import propose_action
from app.core.mcp_oauth import issue_companion_mcp_access_token
from app.core.openai_client import get_openai_client
from app.core.openai_responses import OpenAIResponseError, ensure_response_completed
from app.core.qa import SourceSegment, retrieve_context
from app.core.tool_router import (
    REQUEST_TOOL_GROUP_NAME,
    request_tool_group_tool,
    requestable_groups,
    visible_tool_names,
)
from app.core.tool_safety import is_mutating_tool_call
from app.models.companion import ChatMessage, Conversation
from app.models.recording import ActionItem, Folder, Recording, Segment, Summary
from app.models.user import User
from app.models.user_memory import UserMemoryBlock

logger = logging.getLogger(__name__)

COMPANION_AUTO_TITLE_MAX_CHARS = 72

TOOL_CALL_CAP = 6
HISTORY_WINDOW = 20
ARTIFACT_MAX_CONTENT_CHARS = 60000
SNIPPET_CHAR_CAP = 400
WEB_CITATION_MAX_TITLE_CHARS = 180
WEB_CITATION_MAX_URL_CHARS = 2048
# A streaming assistant message is checkpointed to the DB every N text deltas so
# a dropped SSE stream resumes from the persisted partial instead of losing it.
CHECKPOINT_EVERY_N_DELTAS = 40
# A 'streaming' row older than this with no terminal status is a crashed or
# abandoned turn; the sweep marks it 'failed' (no forever-streaming ghost, and
# no silent success).
STREAMING_TURN_STALE_SECONDS = 120

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

# Used INSTEAD of _IDENTITY_SECTION on action-capable turns so the model stops
# behaving like a read-only Q&A bot and actually reaches for its hands. Read-only
# turns keep _IDENTITY_SECTION verbatim so their cacheable prefix never changes.
_IDENTITY_SECTION_WITH_ACTIONS = (
    "<identity>\n"
    "You are Wai — a calm, precise partner. You answer over the user's "
    "recorded conversations, notes, and reflections, and you can also take "
    "actions on their behalf using the tools below.\n"
    "</identity>"
)

# Injected ONLY on action-capable turns. States, in cacheable prose, the same
# act-vs-ask contract that tool_safety.is_mutating_tool_call enforces in code:
# reads + web_search are automatic; anything that leaves the device is proposed
# for approval first. The code gate stays authoritative — this only aligns model
# behaviour with it so the action path actually fires.
_ACTION_POLICY_SECTION = (
    "<action_policy>\n"
    "You have hands, not just answers.\n"
    "- Look things up freely, without asking: the WaiComputer MCP tools (the "
    "user's own library) and web_search (the public internet). Never ask for "
    "permission to search or read — do it, then answer.\n"
    "- Acting in the world is gated: sending a message, writing to an external "
    "service, or controlling the user's Mac is PROPOSED first and runs only "
    "after the user approves it. Propose one concrete action and stop; never "
    "claim an action is done before it has been approved.\n"
    "- Prefer doing over describing how to do it. Cite the user's library for "
    "their own data and the web for external facts.\n"
    "</action_policy>"
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
    *,
    with_actions: bool = False,
) -> str:
    """Assemble the cacheable system prompt for a turn.

    Order: identity → user_profile → memory → tool_guidance → [action_policy] →
    answer_format. The first three sections vary per user but rarely; the rest
    are static. With `prompt_cache_key` keyed to user_id this keeps a stable
    prefix that's well above the 1024-token cache warm threshold once
    user_profile and memory accumulate.

    `with_actions` swaps in the capability-aware identity and appends
    <action_policy>. It is False for read-only turns so their cacheable prefix
    stays byte-for-byte identical — the prompt cache for read turns is untouched,
    and a client without the actions capability sees exactly the historical prompt.
    """
    identity = _IDENTITY_SECTION_WITH_ACTIONS if with_actions else _IDENTITY_SECTION
    sections: list[str] = [identity]
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
    if with_actions:
        sections.append(_ACTION_POLICY_SECTION)
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
    # The assistant row is created up front (status='streaming') so a reload can
    # reconstruct an in-flight turn; this id is stable through to DoneEvent.
    assistant_message_id: str = ""
    # The chat's current title (instant truncation on the first turn) so the
    # inbox row can title itself live; an async job may refine it afterwards.
    title: str = ""


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
    ok: bool = True


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


@dataclass(frozen=True)
class ActionProposedEvent:
    """A mutating tool (send / external write / desktop action) is proposed and
    awaiting the user's explicit approval. The side effect has NOT run. The
    client shows a confirm sheet and resolves it via /actions/{id}/resolve.
    `preview` is a privacy-safe human-readable dry-run; `recipient` is the
    resolved display name (never a raw id)."""

    type: Literal["action_proposed"] = "action_proposed"
    action_id: str = ""
    kind: str = ""  # send | mutate | desktop_action
    tool: str = ""
    preview: str = ""
    expires_at: str = ""
    recipient: str | None = None


@dataclass(frozen=True)
class ActionResultEvent:
    """The outcome of a resolved pending action."""

    type: Literal["action_result"] = "action_result"
    action_id: str = ""
    status: str = ""  # executed | rejected | expired | failed
    detail: str = ""
    undo_token: str | None = None


@dataclass(frozen=True)
class NarrationEvent:
    """A short spoken status the client reads aloud during a multi-step action
    ("Opening Mail…", "Drafted the reply — say send to send")."""

    type: Literal["narration"] = "narration"
    text: str = ""


@dataclass(frozen=True)
class DesktopActionEvent:
    """A computer-use command the cloud brain emits for the macOS edge to run
    locally; the Mac POSTs the typed result back to /desktop_result. `command`
    is an AXorcist CommandEnvelope (opaque to the backend)."""

    type: Literal["desktop_action"] = "desktop_action"
    action_id: str = ""
    command: dict[str, Any] = field(default_factory=dict)
    device_target: str | None = None


@dataclass(frozen=True)
class ThinkingEvent:
    """A streamed reasoning-summary delta — the model's private thinking,
    surfaced so the client can show a collapsible "Thinking" block. Gated behind
    the agent_chat_v2 capability and only emitted when reasoning is requested
    (chat), never on the low-latency voice path."""

    type: Literal["thinking"] = "thinking"
    text: str = ""


@dataclass(frozen=True)
class PlanEvent:
    """The agent's working checklist for a multi-step task, posted/updated via
    the update_plan tool so the client can render a live plan card with
    checkmarks. Each step is {"title": str, "status": pending|in_progress|done}.
    Gated behind agent_chat_v2."""

    type: Literal["plan"] = "plan"
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactEvent:
    """A self-contained document the agent produced (HTML page / Markdown doc /
    code) for the user to preview and open — rendered as a preview card. Gated
    behind agent_chat_v2."""

    type: Literal["artifact"] = "artifact"
    artifact_id: str = ""
    title: str = ""
    kind: str = "markdown"  # html | markdown | code
    content: str = ""
    language: str = ""


@dataclass(frozen=True)
class WebCitationsEvent:
    """Public web source links returned by the hosted web_search tool.

    Responses API web search exposes these as url_citation annotations on the
    completed message output item. They are separate from private transcript
    citations and contain only public title/URL/span metadata.
    """

    type: Literal["web_citations"] = "web_citations"
    citations: list[dict[str, Any]] = field(default_factory=list)


CompanionEvent = (
    TurnStartEvent
    | ToolCallEvent
    | ToolResultEvent
    | ThinkingEvent
    | PlanEvent
    | ArtifactEvent
    | WebCitationsEvent
    | TokenEvent
    | CitationEvent
    | MemoryUpdatedEvent
    | ActionProposedEvent
    | ActionResultEvent
    | NarrationEvent
    | DesktopActionEvent
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


def _scope_brain_space_uuid(scope: dict[str, Any] | None) -> uuid.UUID | None:
    if not scope:
        return None
    raw = scope.get("brain_space_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise CompanionError(
            "invalid_scope",
            f"Conversation scope has malformed brain_space_id: {exc}",
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


async def _has_searchable_transcript_segments(
    db: AsyncSession,
    user_id: uuid.UUID,
    recording_ids: list[uuid.UUID] | None,
) -> bool:
    stmt = (
        select(Segment.id)
        .join(Recording, Segment.recording_id == Recording.id)
        .where(
            Recording.user_id == user_id,
            Recording.deleted_at.is_(None),
        )
        .limit(1)
    )
    if recording_ids is not None:
        if not recording_ids:
            return False
        stmt = stmt.where(Segment.recording_id.in_(recording_ids))
    return (await db.scalar(stmt)) is not None


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

    if not await _has_searchable_transcript_segments(db, user_id, recording_ids):
        return ToolExecutionResult(
            summary_for_event="0 segments",
            payload_for_model={"segments": []},
            citable_segments={},
        )

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
        .where(
            ChatMessage.conversation_id == conversation_id,
            # Only finalized turns feed the model. An in-flight ('streaming') or
            # crashed ('failed') assistant row must never poison the next prompt.
            ChatMessage.status == "complete",
        )
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
    brain_id = scope.get("brain_space_id") if isinstance(scope, dict) else None
    rec_ids = scope.get("recording_ids") if isinstance(scope, dict) else None
    parts: list[str] = []
    if brain_id:
        parts.append("selected Brain")
    if rec_ids:
        n = len(rec_ids)
        parts.append(f"{n} pinned recording{'s' if n != 1 else ''}")
    if parts:
        return " + ".join(parts)
    return "all of the user's recordings"


async def _brain_context_for_scope(
    db: AsyncSession,
    user_id: uuid.UUID,
    scope: dict[str, Any] | None,
) -> dict[str, Any] | None:
    space_id = _scope_brain_space_uuid(scope)
    if space_id is None:
        return None
    try:
        return await brain_space_service.build_context(
            db,
            user_id=user_id,
            space_id=space_id,
            limit=80,
        )
    except brain_space_service.BrainSpaceNotFoundError as exc:
        raise CompanionError(
            "invalid_scope",
            "Conversation Brain scope is not available to this user.",
        ) from exc
    except brain_space_service.BrainSpacePermissionError as exc:
        raise CompanionError(
            "invalid_scope",
            "Conversation Brain scope is not available to this user.",
        ) from exc
    except brain_space_service.BrainSpaceValidationError as exc:
        raise CompanionError("invalid_scope", str(exc)) from exc


def _build_session_developer_message(
    ctx: TurnContext | None,
    scope: dict[str, Any] | None,
    *,
    brain_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Render the per-turn developer message describing date / tz / scope /
    what the user is currently viewing. Goes in `input` (not `instructions`)
    so the cacheable prefix is stable across turns.

    Returns None when there is genuinely nothing to say (ctx is None and
    scope is empty) — keeps short test fixtures clean.
    """
    if ctx is None and not scope and brain_context is None:
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
    if brain_context is not None:
        space = brain_context.get("space")
        space_name = getattr(space, "name", None) or "selected Brain"
        claim_count = int(brain_context.get("claim_count") or 0)
        lines.append(f"brain: {space_name}; approved items: {claim_count}")
        markdown = str(brain_context.get("markdown") or "").strip()
        if markdown:
            lines.append("<brain_context>")
            lines.append(markdown)
            lines.append("</brain_context>")
        else:
            lines.append("brain_context: no approved knowledge yet")
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


# ---------- Action (write) tools — gated function tools for the actions loop ----------


def _action_tool_defs() -> dict[str, dict[str, Any]]:
    """OpenAI function-tool schemas for write actions. Reads stay on the MCP
    tool; these are the gated 'hands', attached only when their ToolRouter group
    is active, and every call routes through the host approval gate."""
    return {
        "send_message_telegram": {
            "type": "function",
            "name": "send_message_telegram",
            "description": (
                "Send a short Telegram message to the user's OWN Wai chat (when "
                "they say 'message me', 'remind me', 'text myself'). The message "
                "is shown to the user for explicit approval before it is sent — "
                "never assume it was sent. Provide only `text`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The message body."}
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        "desktop_open": {
            "type": "function",
            "name": "desktop_open",
            "description": (
                "Open an app or URL on the user's Mac (e.g. a Gmail compose URL, "
                "a website, an app). Deterministic, low-risk. Requires approval "
                "and runs on the user's Mac, not the server."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "An app name, https URL, or mailto:/compose URL.",
                    }
                },
                "required": ["target"],
                "additionalProperties": False,
            },
        },
        "desktop_type": {
            "type": "function",
            "name": "desktop_type",
            "description": (
                "Type text into the currently focused field on the user's Mac. "
                "Requires approval; runs on the Mac."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type."}
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        "desktop_click": {
            "type": "function",
            "name": "desktop_click",
            "description": (
                "Click a UI element by its index from the latest accessibility "
                "snapshot of the user's Mac. Requires approval; runs on the Mac."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "Element index from a prior snapshot.",
                    }
                },
                "required": ["index"],
                "additionalProperties": False,
            },
        },
    }


UPDATE_PLAN_NAME = "update_plan"


def _update_plan_tool() -> dict[str, Any]:
    """Always-on tool: the model posts a short checklist so the client can show a
    live plan card. Auto-run (no approval) — it only emits a UI event."""
    return {
        "type": "function",
        "name": UPDATE_PLAN_NAME,
        "description": (
            "Post or update a SHORT checklist (2-6 steps) of what you will do "
            "for a multi-step task, so the user can watch progress. Call it once "
            "near the start with steps as 'pending'/'in_progress', then again to "
            "mark steps 'done' as you finish them. Skip it for simple one-shot "
            "answers — never use it for trivial replies."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done"],
                            },
                        },
                        "required": ["title", "status"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["steps"],
            "additionalProperties": False,
        },
    }


def _normalize_plan_steps(raw: Any) -> list[dict[str, str]]:
    """Coerce model-supplied plan steps to a safe, bounded shape for the client."""
    if not isinstance(raw, list):
        return []
    steps: list[dict[str, str]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:120]
        if not title:
            continue
        status = str(item.get("status") or "pending")
        if status not in ("pending", "in_progress", "done"):
            status = "pending"
        steps.append({"title": title, "status": status})
    return steps


CREATE_ARTIFACT_NAME = "create_artifact"


_TASK_LIKE_RE = re.compile(
    r"\b("
    r"find|search|research|compare|analy[sz]e|summari[sz]e|create|build|make|"
    r"generate|write|draft|plan|check|audit|investigate|collect|prepare|"
    r"remember|open|send|list"
    r")\b"
    r"|(?:"
    r"найди|ищи|поиск|сравни|проанализируй|анализ|суммируй|создай|сделай|"
    r"сгенерируй|напиши|подготовь|проверь|аудит|исследуй|собери|запомни|"
    r"открой|отправь|перечисли"
    r")",
    re.IGNORECASE,
)
_COMPLEX_CONNECTOR_RE = re.compile(
    r"\b(and then|then|also|after that|first|second|finally)\b|(?:\bи\b|\bпотом\b|\bзатем\b)",
    re.IGNORECASE,
)


def _task_plan_for_user_text(user_text: str) -> list[dict[str, str]]:
    """Return a short host-side plan for task-like prompts.

    The model can replace this by calling update_plan. This scaffold is only a
    UX contract: it makes long tasks visibly alive even when the model answers
    without using the plan tool. It is deliberately generic so it cannot invent
    work that the model has not performed.
    """
    text = " ".join(user_text.split())
    if not text:
        return []
    looks_task_like = bool(_TASK_LIKE_RE.search(text))
    looks_complex = len(text) >= 96 and bool(_COMPLEX_CONNECTOR_RE.search(text))
    if not looks_task_like and not looks_complex:
        return []

    if _looks_russian(text):
        return [
            {"title": "Понять задачу", "status": "in_progress"},
            {"title": "Проверить нужные источники и инструменты", "status": "pending"},
            {"title": "Выдать результат", "status": "pending"},
        ]
    return [
        {"title": "Understand the task", "status": "in_progress"},
        {"title": "Check the needed sources and tools", "status": "pending"},
        {"title": "Deliver the result", "status": "pending"},
    ]


def _advance_host_plan_for_tool_call(
    steps: list[dict[str, str]],
) -> list[dict[str, str]]:
    if len(steps) < 3:
        return steps
    next_steps = [dict(step) for step in steps]
    next_steps[0]["status"] = "done"
    next_steps[1]["status"] = "in_progress"
    next_steps[2]["status"] = "pending"
    return next_steps


def _complete_host_plan(steps: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{**step, "status": "done"} for step in steps]


def _approval_host_plan(
    user_text: str,
    steps: list[dict[str, str]],
) -> list[dict[str, str]]:
    if len(steps) < 3:
        return steps
    next_steps = [dict(step) for step in steps]
    next_steps[0]["status"] = "done"
    next_steps[1]["status"] = "done"
    next_steps[2] = {
        "title": "Ждать подтверждения" if _looks_russian(user_text) else "Wait for approval",
        "status": "in_progress",
    }
    return next_steps


def _create_artifact_tool() -> dict[str, Any]:
    """Always-on tool: the agent produces a self-contained document (HTML / Markdown
    / code) shown as a preview card. Auto-run — it only emits a UI event."""
    return {
        "type": "function",
        "name": CREATE_ARTIFACT_NAME,
        "description": (
            "Produce a self-contained document the user can preview and open: a web "
            "page (kind=html — return a COMPLETE standalone HTML document), a written "
            "document (kind=markdown), or code (kind=code, set language). Use this for "
            "substantial generated content (a landing page, a draft, a script) instead "
            "of dumping it inline — the user sees a live preview card. Keep the chat "
            "reply short and refer to the artifact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "kind": {"type": "string", "enum": ["html", "markdown", "code"]},
                "content": {"type": "string"},
                "language": {
                    "type": "string",
                    "description": "Programming language when kind=code (e.g. python).",
                },
            },
            "required": ["title", "kind", "content"],
            "additionalProperties": False,
        },
    }


def _artifact_event_from_args(call_id: str | None, args: dict[str, Any]) -> ArtifactEvent:
    kind = str(args.get("kind") or "markdown")
    if kind not in ("html", "markdown", "code"):
        kind = "markdown"
    return ArtifactEvent(
        artifact_id=str(call_id or uuid.uuid4().hex),
        title=(str(args.get("title") or "").strip()[:120] or "Artifact"),
        kind=kind,
        content=str(args.get("content") or "")[:ARTIFACT_MAX_CONTENT_CHARS],
        language=str(args.get("language") or "").strip()[:40],
    )


def _stored_artifact_tool_call(event: ArtifactEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "artifact_id": event.artifact_id,
        "title": event.title,
        "kind": event.kind,
        "content": event.content,
        "language": event.language,
    }


def _stored_action_proposal_tool_call(event: ActionProposedEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "action_id": event.action_id,
        "kind": event.kind,
        "tool": event.tool,
        "preview": event.preview,
        "expires_at": event.expires_at,
        "recipient": event.recipient,
    }


def _stored_plan_tool_call(steps: list[dict[str, str]]) -> dict[str, Any]:
    return {"type": "plan", "steps": steps}


def _stored_web_citations_tool_call(citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "web_citations", "citations": citations}


def _upsert_stored_plan_tool_call(
    tool_calls: list[dict[str, Any]],
    item: dict[str, Any],
) -> None:
    for index, existing in enumerate(tool_calls):
        if existing.get("type") == "plan":
            tool_calls[index] = item
            return
    tool_calls.append(item)


def _stored_tools_tool_call(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    for existing in tool_calls:
        if existing.get("type") == "tools":
            if not isinstance(existing.get("actions"), list):
                existing["actions"] = []
            return existing
    item: dict[str, Any] = {"type": "tools", "actions": []}
    tool_calls.append(item)
    return item


def _append_stored_tool_action(
    tool_calls: list[dict[str, Any]],
    event: ToolCallEvent,
) -> None:
    if not event.call_id or not event.tool:
        return
    item = _stored_tools_tool_call(tool_calls)
    actions = item["actions"]
    actions.append(
        {
            "call_id": event.call_id,
            "tool": event.tool,
            "summary": None,
            "ok": None,
        }
    )


def _apply_stored_tool_result(
    tool_calls: list[dict[str, Any]],
    event: ToolResultEvent,
) -> None:
    if not event.call_id:
        return
    for item in reversed(tool_calls):
        if item.get("type") != "tools" or not isinstance(item.get("actions"), list):
            continue
        for action in reversed(item["actions"]):
            if isinstance(action, dict) and action.get("call_id") == event.call_id:
                action["summary"] = event.summary
                action["ok"] = event.ok
                return


def _visible_action_tools(active_groups: set[str]) -> list[dict[str, Any]]:
    names = set(visible_tool_names(active_groups))
    return [d for n, d in _action_tool_defs().items() if n in names]


def _action_kind(tool_name: str) -> str:
    """desktop_* tools execute on the Mac edge; everything else sends/mutates
    server-side. Determines the pending-action kind (and thus dispatch path)."""
    return "desktop_action" if tool_name.startswith("desktop_") else "send"


def _action_preview(name: str, args: dict[str, Any]) -> tuple[str, str | None]:
    """Privacy-safe human-readable dry-run + resolved recipient display name."""
    if name == "send_message_telegram":
        text = str(args.get("text", "")).strip()
        return (f"Send a Telegram message to you: “{text}”", "you")
    if name == "desktop_open":
        return (f"Open on your Mac: {str(args.get('target', '')).strip()}", None)
    if name == "desktop_type":
        return ("Type into the focused field on your Mac", None)
    if name == "desktop_click":
        return (f"Click element {args.get('index')} on your Mac", None)
    return (f"Run {name}", None)


def _looks_russian(text: str) -> bool:
    return any("а" <= char.casefold() <= "я" or char.casefold() == "ё" for char in text)


def _approval_waiting_text(user_text: str, preview: str) -> str:
    if _looks_russian(user_text):
        return f"Жду твоего подтверждения: {preview}"
    return f"Waiting for your approval: {preview}"


async def _begin_assistant_message(
    db: AsyncSession, conversation_id: uuid.UUID, model: str
) -> ChatMessage:
    """Create the assistant row up front (status='streaming') and flush it for a
    durable id, so a dropped SSE stream resumes from the persisted partial via
    get_chat instead of losing the whole turn."""
    msg = ChatMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=[{"type": "text", "text": ""}],
        model=model,
        status="streaming",
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg)
    return msg


async def _checkpoint_assistant_text(
    db: AsyncSession, message_id: uuid.UUID, text: str
) -> None:
    """Persist the partial answer mid-stream (throttled by the caller) so a
    reload shows the answer-in-progress, not an empty bubble."""
    await db.execute(
        update(ChatMessage)
        .where(ChatMessage.id == message_id)
        .values(content=[{"type": "text", "text": text}])
    )
    await db.commit()


async def _finalize_assistant_message(
    db: AsyncSession,
    *,
    message: ChatMessage,
    conv: Conversation,
    text: str,
    usage: Any,
    latency_ms: int,
    model: str,
    tool_calls: list[Any] | None = None,
) -> tuple[int, int, int]:
    """Write the final answer + usage and flip status to 'complete'. Mutates the
    ORM rows (expire_on_commit is False, so a same-session reader sees the fresh
    values) then commits. Returns (input, output, cached) token counts."""
    input_tokens = _get_usage(usage, "input_tokens")
    output_tokens = _get_usage(usage, "output_tokens")
    cached_tokens = _get_usage(usage, "cached_tokens")
    message.content = [{"type": "text", "text": text}]
    message.tool_calls = tool_calls or None
    message.input_tokens = input_tokens or None
    message.output_tokens = output_tokens or None
    message.cached_tokens = cached_tokens or None
    message.model = model
    message.latency_ms = latency_ms
    message.status = "complete"
    conv.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return input_tokens, output_tokens, cached_tokens


async def _fail_assistant_message(db: AsyncSession, message_id: uuid.UUID) -> None:
    """Mark a turn that errored mid-stream as 'failed' so a reopened thread shows
    a failed turn, never a forever-'streaming' ghost. Best-effort: the sweep
    (sweep_stale_streaming_messages) is the backstop if this cannot run."""
    try:
        await db.rollback()
        await db.execute(
            update(ChatMessage)
            .where(ChatMessage.id == message_id)
            .values(status="failed")
        )
        await db.commit()
    except Exception:  # pragma: no cover - defensive; sweep is the backstop
        logger.warning("could not mark companion assistant message failed")


async def sweep_stale_streaming_messages(
    db: AsyncSession,
    *,
    older_than_seconds: int = STREAMING_TURN_STALE_SECONDS,
    now: datetime | None = None,
) -> int:
    """Fail-closed backstop for crashed turns: flip 'streaming' assistant rows
    older than the cutoff to 'failed'. Returns the number swept."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=older_than_seconds)
    result = await db.execute(
        update(ChatMessage)
        .where(
            ChatMessage.role == "assistant",
            ChatMessage.status == "streaming",
            ChatMessage.created_at <= cutoff,
        )
        .values(status="failed")
    )
    return result.rowcount or 0


async def run_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_text: str,
    *,
    turn_context: TurnContext | None = None,
    openai_client=None,
    enable_actions: bool = False,
    stream_reasoning: bool = False,
) -> AsyncIterator[CompanionEvent]:
    settings = get_settings()
    client = openai_client if openai_client is not None else get_openai_client()
    started = time.monotonic()

    conv = await _load_conversation_locked(db, user_id, conversation_id)
    user_row = await db.get(User, user_id)
    memory_blocks = await user_memory_module.get_or_seed_blocks(db, user_id)
    instructions = system_prompt_for(
        user_row, memory_blocks=memory_blocks, with_actions=enable_actions
    )

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

    # Create the assistant row up front (status='streaming') so a dropped stream
    # never loses the turn — a reload reconstructs it from the persisted partial.
    assistant_msg = await _begin_assistant_message(
        db, conv.id, settings.openai_llm_model
    )
    assistant_message_id = str(assistant_msg.id)

    yield TurnStartEvent(
        message_id=str(user_msg.id),
        conversation_id=str(conv.id),
        assistant_message_id=assistant_message_id,
        title=conv.title or "",
    )

    history = await _load_history(db, conv.id)
    base_input = _history_to_responses_input(history)
    brain_context = await _brain_context_for_scope(db, user_id, conv.scope)
    session_message = _build_session_developer_message(
        turn_context,
        conv.scope,
        brain_context=brain_context,
    )
    response_input: list[dict[str, Any]] = []
    if session_message is not None:
        response_input.append(session_message)
    response_input.extend(base_input)

    access_token = await issue_companion_mcp_access_token(db, user_id)
    # OpenAI calls the remote MCP server from outside this DB transaction.
    # Commit the just-issued token (the user turn + the streaming assistant row)
    # before the stream starts so `/mcp` can resolve the presented token on its
    # own connection and a reload already sees the in-flight turn.
    await db.commit()
    mcp_tool = _companion_mcp_tool(settings, access_token)

    if enable_actions:
        try:
            async for _evt in _run_actions_loop(
                db,
                client,
                settings,
                user_id,
                conv,
                user_msg,
                assistant_msg,
                instructions,
                response_input,
                mcp_tool,
                started,
                stream_reasoning,
            ):
                yield _evt
        except Exception:
            await _fail_assistant_message(db, assistant_msg.id)
            raise
        return

    assistant_text = ""
    usage: Any = None
    completed_response_obj: Any = None
    persisted_tool_calls: list[dict[str, Any]] = []
    delta_count = 0
    try:
        stream = await client.responses.create(
            model=settings.openai_llm_model,
            instructions=instructions,
            input=response_input,
            tools=[mcp_tool],
            prompt_cache_key=f"wai-companion-{user_id}",
            stream=True,
            **({"reasoning": {"summary": "auto"}} if stream_reasoning else {}),
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
                    delta_count += 1
                    if delta_count % CHECKPOINT_EVERY_N_DELTAS == 0:
                        await _checkpoint_assistant_text(
                            db, assistant_msg.id, assistant_text
                        )
            elif event_type == "response.output_item.added":
                _tc = _tool_call_event_from_item(_stream_event_item(event))
                if _tc is not None:
                    _append_stored_tool_action(persisted_tool_calls, _tc)
                    yield _tc
            elif event_type == "response.output_item.done":
                _tr = _tool_result_event_from_item(_stream_event_item(event))
                if _tr is not None:
                    _apply_stored_tool_result(persisted_tool_calls, _tr)
                    yield _tr
            elif event_type == "response.reasoning_summary_text.delta":
                rdelta = getattr(event, "delta", None)
                if rdelta is None and isinstance(event, dict):
                    rdelta = event.get("delta", "")
                if rdelta:
                    yield ThinkingEvent(text=rdelta)
            elif event_type in ("response.completed", "response.done"):
                response_obj = getattr(event, "response", None)
                if response_obj is None and isinstance(event, dict):
                    response_obj = event.get("response")
                if response_obj is not None:
                    completed_response_obj = response_obj
                    try:
                        ensure_response_completed(
                            response_obj, operation="Companion response"
                        )
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
    except Exception:
        await _fail_assistant_message(db, assistant_msg.id)
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    web_citations = _extract_web_citations(completed_response_obj)
    if web_citations:
        yield WebCitationsEvent(citations=web_citations)
    mcp_context_items = _extract_mcp_context_items(completed_response_obj)
    stored_tool_calls = persisted_tool_calls
    if web_citations:
        stored_tool_calls = stored_tool_calls + [
            _stored_web_citations_tool_call(web_citations)
        ]
    stored_tool_calls = stored_tool_calls + mcp_context_items
    input_tokens, output_tokens, cached_tokens = await _finalize_assistant_message(
        db,
        message=assistant_msg,
        conv=conv,
        text=assistant_text,
        usage=usage,
        latency_ms=latency_ms,
        model=settings.openai_llm_model,
        tool_calls=stored_tool_calls or None,
    )

    yield DoneEvent(
        message_id=assistant_message_id,
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        cached_tokens=cached_tokens or None,
        model=settings.openai_llm_model,
        latency_ms=latency_ms,
    )


async def _run_actions_loop(
    db: AsyncSession,
    client: Any,
    settings: Any,
    user_id: uuid.UUID,
    conv: Conversation,
    user_msg: ChatMessage,
    assistant_msg: ChatMessage,
    instructions: str,
    response_input: list[dict[str, Any]],
    mcp_tool: dict[str, Any],
    started: float,
    stream_reasoning: bool = False,
) -> AsyncIterator[CompanionEvent]:
    """Bounded function-tool loop for action-capable turns.

    Reads still go via the MCP tool; write 'hands' are gated function tools
    attached on demand (request_tool_group). A mutating call is proposed to the
    approval gate and the turn DEFERS — the side effect runs only after
    /resolve. Bounded by TOOL_CALL_CAP; errors surface (no fallback). The
    assistant row (created 'streaming' before the loop) is finalized here; the
    caller flips it to 'failed' if this loop raises.
    """
    active_groups: set[str] = set()
    prev_response_id: str | None = None
    next_input: list[dict[str, Any]] = response_input
    usage: Any = None
    final_text = ""
    proposed = False
    proposed_preview: str | None = None
    persisted_tool_calls: list[dict[str, Any]] = []
    web_citations: list[dict[str, Any]] = []
    host_plan = _task_plan_for_user_text(_message_content_to_text(user_msg.content))
    model_plan_seen = False
    if host_plan:
        yield PlanEvent(steps=host_plan)
        _upsert_stored_plan_tool_call(
            persisted_tool_calls,
            _stored_plan_tool_call(host_plan),
        )

    for step in range(1, TOOL_CALL_CAP + 1):
        # mcp_tool = read access to the user's brain; the hosted web_search tool
        # = "find this on the internet" (runs server-side). Hosted results are
        # not interceptable, so the propose->commit write gate (every send/OS
        # action confirmed) is the lethal-trifecta control, not result-wrapping.
        tools: list[dict[str, Any]] = [
            mcp_tool,
            {"type": "web_search"},
            _update_plan_tool(),
            _create_artifact_tool(),
        ]
        if requestable_groups("voice_default"):
            tools.append(request_tool_group_tool("voice_default"))
        tools.extend(_visible_action_tools(active_groups))

        create_kwargs: dict[str, Any] = dict(
            model=settings.openai_llm_model,
            instructions=instructions,
            tools=tools,
            prompt_cache_key=f"wai-companion-{user_id}",
            stream=True,
            input=next_input,
        )
        if stream_reasoning:
            create_kwargs["reasoning"] = {"summary": "auto"}
        if prev_response_id is not None:
            create_kwargs["previous_response_id"] = prev_response_id

        stream = await client.responses.create(**create_kwargs)
        step_text = ""
        completed: Any = None
        async for event in stream:
            etype = getattr(event, "type", None) or (
                event.get("type") if isinstance(event, dict) else None
            )
            if etype == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if delta is None and isinstance(event, dict):
                    delta = event.get("delta", "")
                delta = delta or ""
                step_text += delta
                if delta:
                    yield TokenEvent(text=delta)
            elif etype == "response.output_item.added":
                _tc = _tool_call_event_from_item(_stream_event_item(event))
                if _tc is not None:
                    if host_plan and not model_plan_seen:
                        advanced_plan = _advance_host_plan_for_tool_call(host_plan)
                        if advanced_plan != host_plan:
                            host_plan = advanced_plan
                            yield PlanEvent(steps=host_plan)
                            _upsert_stored_plan_tool_call(
                                persisted_tool_calls,
                                _stored_plan_tool_call(host_plan),
                            )
                    _append_stored_tool_action(persisted_tool_calls, _tc)
                    yield _tc
            elif etype == "response.output_item.done":
                _tr = _tool_result_event_from_item(_stream_event_item(event))
                if _tr is not None:
                    _apply_stored_tool_result(persisted_tool_calls, _tr)
                    yield _tr
            elif etype == "response.reasoning_summary_text.delta":
                rdelta = getattr(event, "delta", None)
                if rdelta is None and isinstance(event, dict):
                    rdelta = event.get("delta", "")
                if rdelta:
                    yield ThinkingEvent(text=rdelta)
            elif etype in ("response.completed", "response.done"):
                completed = getattr(event, "response", None)
                if completed is None and isinstance(event, dict):
                    completed = event.get("response")
                if completed is not None:
                    try:
                        ensure_response_completed(
                            completed, operation="Companion response"
                        )
                    except OpenAIResponseError as exc:
                        raise CompanionError("model_incomplete", str(exc)) from exc
                    step_usage = getattr(completed, "usage", None)
                    if step_usage is None and isinstance(completed, dict):
                        step_usage = completed.get("usage")
                    usage = step_usage or usage
                    _merge_web_citations(
                        web_citations, _extract_web_citations(completed)
                    )
                    if not step_text:
                        step_text = _extract_text(completed)
            elif etype in ("response.error", "error"):
                err = getattr(event, "error", None)
                if err is None and isinstance(event, dict):
                    err = event.get("error")
                msg = (
                    getattr(err, "message", None)
                    or (err.get("message") if isinstance(err, dict) else None)
                    or "Companion stream failed"
                )
                raise CompanionError("stream_error", str(msg))

        if step_text:
            final_text = step_text
            await _checkpoint_assistant_text(db, assistant_msg.id, final_text)
        calls = _extract_tool_calls(completed)
        if not calls:
            break  # model produced a final answer

        prev_response_id = getattr(completed, "id", None)
        if prev_response_id is None and isinstance(completed, dict):
            prev_response_id = completed.get("id")

        outputs: list[dict[str, Any]] = []
        for call in calls:
            cname = call.get("name") or ""
            cargs = call.get("arguments") or {}
            cid = call.get("id")
            if cname == REQUEST_TOOL_GROUP_NAME:
                group = str(cargs.get("group", ""))
                active_groups.add(group)
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": cid,
                        "output": json.dumps({"ok": True, "attached": group}),
                    }
                )
            elif cname == UPDATE_PLAN_NAME:
                plan_steps = _normalize_plan_steps(cargs.get("steps"))
                if plan_steps:
                    model_plan_seen = True
                    host_plan = []
                    yield PlanEvent(steps=plan_steps)
                    _upsert_stored_plan_tool_call(
                        persisted_tool_calls,
                        _stored_plan_tool_call(plan_steps),
                    )
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": cid,
                        "output": json.dumps({"ok": True}),
                    }
                )
            elif cname == CREATE_ARTIFACT_NAME:
                artifact_event = _artifact_event_from_args(cid, cargs)
                yield artifact_event
                persisted_tool_calls.append(_stored_artifact_tool_call(artifact_event))
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": cid,
                        "output": json.dumps({"ok": True}),
                    }
                )
            elif is_mutating_tool_call(cname, cargs):
                preview, recipient = _action_preview(cname, cargs)
                idempotency_key = f"{conv.id}:{user_msg.id}:{step}:{cname}"
                row = await propose_action(
                    db,
                    user_id=user_id,
                    conversation_id=conv.id,
                    kind=_action_kind(cname),
                    tool_name=cname,
                    args=cargs,
                    preview=preview,
                    idempotency_key=idempotency_key,
                    recipient_display=recipient,
                )
                await db.commit()  # register BEFORE surfacing (race-fix)
                proposal_event = ActionProposedEvent(
                    action_id=str(row.id),
                    kind=_action_kind(cname),
                    tool=cname,
                    preview=preview,
                    expires_at=row.expires_at.isoformat(),
                    recipient=recipient,
                )
                yield proposal_event
                persisted_tool_calls.append(
                    _stored_action_proposal_tool_call(proposal_event)
                )
                proposed = True
                proposed_preview = proposed_preview or preview
            else:
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": cid,
                        "output": json.dumps(
                            {"ok": False, "error": f"tool {cname} unavailable"}
                        ),
                    }
                )
        if proposed:
            if not final_text.strip() and proposed_preview:
                final_text = _approval_waiting_text(
                    _message_content_to_text(user_msg.content),
                    proposed_preview,
                )
                yield TokenEvent(text=final_text)
            break  # defer for human approval; do not continue the loop
        next_input = outputs

    text_to_store = final_text.strip()
    if not text_to_store and not proposed:
        raise CompanionError(
            "empty_model_output",
            "Companion stream completed without emitting any text.",
        )
    if web_citations:
        yield WebCitationsEvent(citations=web_citations)
        persisted_tool_calls.append(_stored_web_citations_tool_call(web_citations))
    if host_plan and not model_plan_seen:
        host_plan = (
            _approval_host_plan(_message_content_to_text(user_msg.content), host_plan)
            if proposed
            else _complete_host_plan(host_plan)
        )
        yield PlanEvent(steps=host_plan)
        _upsert_stored_plan_tool_call(
            persisted_tool_calls,
            _stored_plan_tool_call(host_plan),
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    input_tokens, output_tokens, cached_tokens = await _finalize_assistant_message(
        db,
        message=assistant_msg,
        conv=conv,
        text=text_to_store,
        usage=usage,
        latency_ms=latency_ms,
        model=settings.openai_llm_model,
        tool_calls=persisted_tool_calls or None,
    )
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


def _extract_web_citations(response_obj: Any) -> list[dict[str, Any]]:
    """Extract public web_search url_citation annotations from a completed response."""
    if response_obj is None:
        return []
    output = getattr(response_obj, "output", None)
    if output is None and isinstance(response_obj, dict):
        output = response_obj.get("output")
    output = output or []

    citations: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in output:
        data = _response_item_to_dict(item)
        if data.get("type") != "message":
            continue
        content = data.get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            block_data = _response_item_to_dict(block)
            if block_data.get("type") != "output_text":
                continue
            annotations = block_data.get("annotations") or []
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                annotation_data = _response_item_to_dict(annotation)
                citation = _clean_web_citation(annotation_data)
                if citation is None:
                    continue
                url = citation["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                citations.append(citation)
    return citations


def _clean_web_citation(annotation: dict[str, Any]) -> dict[str, Any] | None:
    if annotation.get("type") != "url_citation":
        return None
    raw_url = annotation.get("url")
    if not isinstance(raw_url, str):
        return None
    url = raw_url.strip()
    if len(url) > WEB_CITATION_MAX_URL_CHARS or not _is_http_url(url):
        return None

    raw_title = annotation.get("title")
    title = (str(raw_title).strip() if raw_title is not None else "") or url
    citation: dict[str, Any] = {
        "title": title[:WEB_CITATION_MAX_TITLE_CHARS],
        "url": url,
    }
    start_index = _int_or_none(annotation.get("start_index"))
    end_index = _int_or_none(annotation.get("end_index"))
    if start_index is not None:
        citation["start_index"] = start_index
    if end_index is not None:
        citation["end_index"] = end_index
    return citation


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merge_web_citations(
    destination: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> None:
    seen_urls = {item.get("url") for item in destination if isinstance(item, dict)}
    for citation in incoming:
        url = citation.get("url")
        if not isinstance(url, str) or url in seen_urls:
            continue
        seen_urls.add(url)
        destination.append(citation)


def _response_item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    data: dict[str, Any] = {}
    for key in (
        "id",
        "type",
        "server_label",
        "tools",
        "content",
        "annotations",
        "text",
        "url",
        "title",
        "start_index",
        "end_index",
    ):
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


# ---- Streaming tool-activity helpers (mcp_call / web_search_call output items) ----
# Hosted reads (the MCP brain query + the web_search tool) execute server-side
# inside OpenAI, so they never appear as local function calls. They DO surface as
# output items in the response stream — we turn each added/done item into a
# ToolCall/ToolResult event so the client can render a live "tool action" card.
# Write 'hands' are function calls and surface as ActionProposedEvent instead, so
# they are deliberately ignored here (no double-surfacing).

_STREAMED_TOOL_ITEM_TYPES = frozenset({"mcp_call", "web_search_call"})
_TOOL_RESULT_LIST_KEYS = (
    "segments",
    "recordings",
    "action_items",
    "highlights",
    "results",
    "folders",
    "matched_entities",
)


def _stream_event_item(event: Any) -> dict[str, Any] | None:
    """Extract the output item carried by a response.output_item.* stream event."""
    item = getattr(event, "item", None)
    if item is None and isinstance(event, dict):
        item = event.get("item")
    if item is None:
        return None
    return _response_item_to_dict(item)


def _tool_call_event_from_item(item: dict[str, Any] | None) -> ToolCallEvent | None:
    if not item or item.get("type") not in _STREAMED_TOOL_ITEM_TYPES:
        return None
    call_id = str(item.get("id") or "")
    if item.get("type") == "web_search_call":
        action = item.get("action") or {}
        query = str(action.get("query") or "") if isinstance(action, dict) else ""
        return ToolCallEvent(
            call_id=call_id, tool="web_search", args={"query": query} if query else {}
        )
    args: dict[str, Any] = {}
    raw_args = item.get("arguments")
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            args = parsed
    elif isinstance(raw_args, dict):
        args = raw_args
    return ToolCallEvent(call_id=call_id, tool=str(item.get("name") or "tool"), args=args)


def _tool_result_event_from_item(item: dict[str, Any] | None) -> ToolResultEvent | None:
    """Map a completed output item to a ToolResultEvent. The summary is a privacy
    safe count/status only — never raw transcript or result content."""
    if not item or item.get("type") not in _STREAMED_TOOL_ITEM_TYPES:
        return None
    call_id = str(item.get("id") or "")
    if item.get("type") == "web_search_call":
        status = str(item.get("status") or "completed")
        ok = status not in ("failed", "incomplete", "error")
        return ToolResultEvent(call_id=call_id, summary="Searched the web", ok=ok)
    ok = not item.get("error")
    return ToolResultEvent(
        call_id=call_id,
        summary=_summarize_tool_output(item.get("output"), ok=ok),
        ok=ok,
    )


def _summarize_tool_output(output: Any, *, ok: bool) -> str:
    if not ok:
        return "Failed"
    data: Any = output
    if isinstance(output, str):
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return "Done"
    if isinstance(data, dict):
        for key in _TOOL_RESULT_LIST_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                n = len(value)
                return f"{n} result{'' if n == 1 else 's'}"
    if isinstance(data, list):
        n = len(data)
        return f"{n} result{'' if n == 1 else 's'}"
    return "Done"


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
