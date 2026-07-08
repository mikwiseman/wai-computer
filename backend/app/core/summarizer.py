"""Cerebras-backed summarization, title generation, and entity extraction."""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.cerebras_chat import (
    CerebrasResponseError,
    chat_completion_parsed,
    chat_completion_text,
    get_cerebras_client,
    strict_json_response_format,
)
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_exception,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class SummarizationError(Exception):
    """Error during summarization."""

    pass


# ---------------------------------------------------------------------------
# Pydantic schemas (drive the model's structured output contract).
# ---------------------------------------------------------------------------


class _Decision(BaseModel):
    decision: str
    context: str


class _ActionItem(BaseModel):
    task: str
    owner: str | None
    due: str | None
    priority: Literal["high", "medium", "low"]


class _Highlight(BaseModel):
    category: Literal["decision", "insight", "question", "concern", "topic_shift", "quote"]
    title: str
    description: str | None
    speaker: str | None
    importance: Literal["high", "medium", "low"]


class _SummarySchema(BaseModel):
    title: str
    summary: str
    key_points: list[str] = Field(max_length=15)
    decisions: list[_Decision] = Field(max_length=20)
    action_items: list[_ActionItem] = Field(max_length=30)
    topics: list[str] = Field(max_length=20)
    people_mentioned: list[str] = Field(max_length=30)
    follow_up_questions: list[str] = Field(max_length=10)
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    highlights: list[_Highlight] = Field(max_length=10)


class _EntityRelation(BaseModel):
    related_to: str
    relation_type: Literal["works_on", "mentioned_with", "related_to"]


class _Entity(BaseModel):
    name: str
    type: Literal["person", "topic", "project", "organization"]
    context: str
    relations: list[_EntityRelation] = Field(max_length=5)


class _EntityExtractionSchema(BaseModel):
    entities: list[_Entity] = Field(max_length=50)


class _KeyMoment(BaseModel):
    # "MM:SS" / "HH:MM:SS" for time-based media; null for articles/text.
    timestamp: str | None
    moment: str
    why_it_matters: str
    quote: str | None
    importance: Literal["high", "medium", "low"]


class _KeyMomentsSchema(BaseModel):
    moments: list[_KeyMoment] = Field(max_length=20)


# ---------------------------------------------------------------------------
# Prompts. The structured-output schema is enforced by ``response_format``, so
# the prompt itself only carries instructions (no JSON shape to repeat).
# ---------------------------------------------------------------------------


SUMMARY_INSTRUCTIONS = """\
You summarize a transcript (a meeting, conversation, lecture, voice note, or
spoken plan). Output one structured object that follows the provided schema.

Rules:
- Do not invent facts. Only include information that is actually present in the
  transcript. If a field is unknown, return null for nullable fields or an empty
  array for lists. Do not pad lists to look complete.
- Hard caps: key_points <= 15, decisions <= 20, action_items <= 30, topics <=
  20, people_mentioned <= 30, follow_up_questions <= 10, highlights <= 10.
- Keep descriptions specific: include names, dates, numbers, and quoted phrases
  when the transcript provides them.
- Identify speakers when possible; leave the speaker null when it is unclear.
- For people_mentioned, list each distinct person exactly once, using their
  canonical name in the nominative case (именительный падеж). Merge grammatical
  cases, short forms, and diminutives of the SAME person into one entry
  (e.g. «Коля»/«Колей» -> «Коля»; «Лёша»/«Лёш»/«Леша» -> «Лёша»). Prefer the
  fullest proper form actually used. Never list the same person twice. Exclude
  diarization speaker labels (speaker_0, Speaker 1) and placeholders — only real
  people named in the content.
- For action_items, set `owner` to the person responsible when the transcript
  makes it clear (a named speaker who is assigned or commits to the task);
  otherwise leave owner null. Never guess an owner.
- The top-level title and each highlight title MUST be plain text: no markdown
  formatting (no **bold**, no *italics*, no _underscores_, no `code`, no #
  headings), and no surrounding quotes. Just the words.
- Limit highlights to the 5-10 most important moments (decisions made, key
  insights, important questions raised, concerns flagged, major topic shifts,
  and notable direct quotes). Each highlight should be a distinct moment.
"""


STYLE_INSTRUCTIONS = {
    "brief": (
        "Keep the summary to 1-2 sentences. "
        "Key points should have at most 3 items. Be concise."
    ),
    "medium": (
        "Write a 2-3 sentence summary. "
        "Include 3-7 key points. Balance detail with brevity."
    ),
    "detailed": (
        "Write a thorough 4-6 sentence summary. "
        "Include all key points discussed (up to 15). "
        "Provide detailed context for decisions and action items."
    ),
    "structured": (
        "Cover the content completely — every distinct point, decision, and action, "
        "with no padding. Do NOT target a sentence count: the length follows the "
        "content, so a one-line note stays one line and a long meeting gets full "
        "coverage."
    ),
}

DEFAULT_SUMMARY_LANGUAGE = "auto"
DEFAULT_SUMMARY_STYLE = "medium"

# Long transcripts that would overflow a single completion's context/budget are
# summarized map-reduce: chunk -> per-chunk structured summary -> merge. Below the
# threshold the original single pass is used unchanged.
MAP_REDUCE_CHAR_THRESHOLD = 40_000
MAP_REDUCE_CHUNK_CHARS = 28_000
MAP_REDUCE_OVERLAP_LINES = 2
MAP_REDUCE_MAX_CONCURRENCY = 4

# gpt-oss reasoning tokens count against max_completion_tokens; 4096 starved
# long-recording summaries (finish_reason=length killed the reduce pass on a
# 74-minute meeting, prod 2026-07-08). Generous base + a one-shot retry ceiling.
SUMMARY_MAX_COMPLETION_TOKENS = 8192
SUMMARY_RETRY_MAX_COMPLETION_TOKENS = 24576


def _require_cerebras_key() -> None:
    if not settings.cerebras_api_key:
        raise ValueError("CEREBRAS_API_KEY not configured")


def _summary_messages(instructions: str, content: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise WaiComputer text processing model. Follow the "
                "developer instructions exactly and return only the requested output."
            ),
        },
        {"role": "user", "content": instructions + content},
    ]


def build_summary_prompt(
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
    style: str = DEFAULT_SUMMARY_STYLE,
    instructions: str | None = None,
) -> str:
    """Build the summarization prompt body (instructions only — schema is enforced separately)."""
    parts = [SUMMARY_INSTRUCTIONS]

    style_text = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS[DEFAULT_SUMMARY_STYLE])
    parts.append(f"\nSTYLE: {style_text}")

    if language and language != DEFAULT_SUMMARY_LANGUAGE:
        parts.append(
            f"\nOUTPUT LANGUAGE: Write ALL text fields "
            f"(title, summary, key_points, etc.) in {language}."
        )
    else:
        parts.append(
            "\nOUTPUT LANGUAGE: Write ALL text fields "
            "(title, summary, key_points, etc.) in the dominant language of the transcript. "
            "If the transcript is primarily in Russian, output Russian. "
            "If the transcript is primarily in English, output English."
        )

    if instructions and instructions.strip():
        parts.append(f"\nADDITIONAL INSTRUCTIONS: {instructions.strip()}")

    parts.append("\nTranscript:\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API (call-site contracts).
# ---------------------------------------------------------------------------


@dataclass
class SummaryResult:
    """Result from summarization."""

    title: str
    summary: str
    key_points: list[str]
    decisions: list[dict]
    action_items: list[dict]
    topics: list[str]
    people_mentioned: list[str]
    follow_up_questions: list[str]
    sentiment: str
    highlights: list[dict] | None = None


async def _summarize_transcript_once(
    transcript: str,
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
    style: str = DEFAULT_SUMMARY_STYLE,
    instructions: str | None = None,
    name: str = "recording_summary",
) -> SummaryResult:
    """One Cerebras strict-structured-output summarization pass.

    gpt-oss reasoning tokens count against ``max_completion_tokens``, and a rich
    structured summary of a long recording can exceed the base budget — the
    completion then stops with ``finish_reason=length`` and the whole summary
    fails (prod 2026-07-08: a 74-minute meeting died on the reduce pass). Retry
    once with a much larger budget before failing.
    """
    _require_cerebras_key()

    prompt = build_summary_prompt(language=language, style=style, instructions=instructions)
    client = get_cerebras_client()

    async def _attempt(max_completion_tokens: int) -> _SummarySchema:
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=_summary_messages(prompt, transcript),
            response_format=strict_json_response_format(_SummarySchema, name=name),
            reasoning_effort="medium",
            max_completion_tokens=max_completion_tokens,
        )
        return chat_completion_parsed(
            response,
            _SummarySchema,
            operation="Summarization",
        )

    try:
        try:
            parsed = await _attempt(SUMMARY_MAX_COMPLETION_TOKENS)
        except CerebrasResponseError as exc:
            if "length" not in str(exc):
                raise
            add_sentry_breadcrumb(
                category="summarizer",
                message="Summarization retry with larger completion budget",
                data={"first_budget": SUMMARY_MAX_COMPLETION_TOKENS},
            )
            parsed = await _attempt(SUMMARY_RETRY_MAX_COMPLETION_TOKENS)
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Summarization failed: {exc}") from exc

    return SummaryResult(
        title=parsed.title,
        summary=parsed.summary,
        key_points=parsed.key_points,
        decisions=[d.model_dump() for d in parsed.decisions],
        action_items=[a.model_dump() for a in parsed.action_items],
        topics=parsed.topics,
        people_mentioned=_strip_speaker_labels(parsed.people_mentioned),
        follow_up_questions=parsed.follow_up_questions,
        sentiment=parsed.sentiment,
        highlights=[h.model_dump() for h in parsed.highlights],
    )


def _chunk_transcript(
    transcript: str,
    *,
    max_chars: int = MAP_REDUCE_CHUNK_CHARS,
    overlap_lines: int = MAP_REDUCE_OVERLAP_LINES,
) -> list[str]:
    """Split a (speaker-labeled) transcript on line boundaries into <=max_chars
    chunks, carrying a few trailing lines into the next chunk for continuity."""
    lines = transcript.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = current[-overlap_lines:] if overlap_lines > 0 else []
            size = sum(len(x) + 1 for x in current)
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _dedup_strings(items: list[str], cap: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = (item or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= cap:
            break
    return out


def _dedup_dicts(items: list[dict], key_field: str, cap: int) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = str(item.get(key_field) or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= cap:
            break
    return out


def _merge_partial_summaries(partials: list[SummaryResult]) -> dict:
    """Deterministically union the structured list fields across chunk summaries."""
    return {
        "key_points": _dedup_strings([p for part in partials for p in part.key_points], cap=15),
        "decisions": _dedup_dicts(
            [d for part in partials for d in part.decisions], "decision", cap=20
        ),
        "action_items": _dedup_dicts(
            [a for part in partials for a in part.action_items], "task", cap=30
        ),
        "topics": _dedup_strings([t for part in partials for t in part.topics], cap=20),
        "people_mentioned": _dedup_strings(
            [p for part in partials for p in part.people_mentioned], cap=30
        ),
        "follow_up_questions": _dedup_strings(
            [q for part in partials for q in part.follow_up_questions], cap=10
        ),
        "highlights": _dedup_dicts(
            [h for part in partials for h in (part.highlights or [])], "title", cap=10
        ),
    }


_SPEAKER_LABEL_RE = re.compile(r"^\s*(?:speaker|спикер|участник)[\s_\-]*\d*\s*$", re.IGNORECASE)


def _strip_speaker_labels(names: list[str]) -> list[str]:
    """Drop diarization placeholders (speaker_0, "Speaker 1", "спикер 2") — never
    real people — that can leak into people_mentioned from speaker-labeled lines."""
    return [n for n in names if n and not _SPEAKER_LABEL_RE.match(n)]


class _PeopleSchema(BaseModel):
    people: list[str] = Field(max_length=30)


PEOPLE_CANONICALIZATION_INSTRUCTIONS = """\
You are given a list of person names extracted from ONE recording. They may
contain Russian grammatical-case forms, short forms, and diminutives of the same
person, plus duplicates and stray non-names.

Return a clean list:
- Each distinct REAL person exactly once, by their canonical name in the
  nominative case (именительный падеж). Merge case-forms, short forms, and
  diminutives of the same person into one entry (Коля/Колей -> Коля;
  Лёша/Лёш/Леша -> Лёша). Prefer the fullest proper form present.
- Drop anything that is not a real person name — diarization speaker labels
  (speaker_0, Speaker 1, спикер 2) and placeholders.
- Do not invent anyone who is not in the input.

Names:
"""


# gpt-oss reasoning tokens count against max_completion_tokens even at
# reasoning_effort="low"; 512 starved the budget on 20-30 name lists and the
# truncated JSON failed whole summaries with finish_reason=length (prod 2026-07).
CANONICALIZATION_MAX_COMPLETION_TOKENS = 2048
CANONICALIZATION_RETRY_MAX_COMPLETION_TOKENS = 4096


async def _canonicalize_people_names(names: list[str], *, language: str) -> list[str]:
    """Collapse Russian case-forms/short-forms/diminutives of the same person into a
    single canonical nominative entry and drop non-name placeholders.

    Used after the map-reduce merge, where per-chunk canonicalization can't dedupe
    people across chunks. Operates on the (clean, complete) merged union — not the
    reduce prose — so diarization speaker labels are never re-introduced.

    This is a cosmetic enrichment of one field: if the LLM pass ultimately fails,
    the summary keeps the deterministic label-stripped dedup (possibly with
    grammatical-case duplicates) instead of failing outright — captured to Sentry,
    never silent.
    """
    cleaned = _dedup_strings(_strip_speaker_labels(names), cap=30)
    if len(cleaned) < 2:
        return cleaned
    client = get_cerebras_client()

    async def _attempt(max_completion_tokens: int) -> list[str]:
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=_summary_messages(PEOPLE_CANONICALIZATION_INSTRUCTIONS, "\n".join(cleaned)),
            response_format=strict_json_response_format(_PeopleSchema, name="people_canon"),
            reasoning_effort="low",
            max_completion_tokens=max_completion_tokens,
        )
        parsed = chat_completion_parsed(
            response, _PeopleSchema, operation="People canonicalization"
        )
        return _dedup_strings(_strip_speaker_labels(parsed.people), cap=30)

    try:
        try:
            return await _attempt(CANONICALIZATION_MAX_COMPLETION_TOKENS)
        except CerebrasResponseError as exc:
            if "length" not in str(exc):
                raise
            return await _attempt(CANONICALIZATION_RETRY_MAX_COMPLETION_TOKENS)
    except Exception as exc:  # noqa: BLE001 — degrade loudly, never fail the summary
        capture_sentry_exception(exc)
        logger.warning(
            "people canonicalization degraded to deterministic dedup "
            "names=%s error_type=%s",
            len(cleaned),
            type(exc).__name__,
        )
        return cleaned


async def _map_reduce_summarize(
    transcript: str,
    *,
    language: str,
    style: str,
    instructions: str | None,
) -> SummaryResult:
    """Summarize a long transcript by chunk (map) then merge (reduce)."""
    chunks = _chunk_transcript(transcript)
    add_sentry_breadcrumb(
        category="summarizer",
        message="Map-reduce summarization",
        data={"chunks": len(chunks), "transcript_length": len(transcript)},
    )
    semaphore = asyncio.Semaphore(MAP_REDUCE_MAX_CONCURRENCY)

    async def _map_one(chunk: str) -> SummaryResult:
        async with semaphore:
            return await _summarize_transcript_once(
                chunk,
                language=language,
                style=style,
                instructions=instructions,
                name="recording_summary_chunk",
            )

    partials = list(await asyncio.gather(*(_map_one(chunk) for chunk in chunks)))
    merged = _merge_partial_summaries(partials)

    # Reduce: synthesize ONE coherent overview from the chunk summaries. The list
    # fields are already comprehensively merged above, so we keep only the
    # synthesized prose + title + sentiment from this pass.
    reduce_instructions = (
        (instructions + "\n\n" if instructions else "")
        + "The text below is an ordered set of section summaries of ONE longer "
        "recording. Produce a single unified summary of the whole recording — do "
        "not mention 'sections' and do not repeat the same point twice."
    )
    combined = "\n\n".join(p.summary.strip() for p in partials if p.summary.strip())
    reduced = await _summarize_transcript_once(
        combined,
        language=language,
        style=style,
        instructions=reduce_instructions,
        name="recording_summary_reduce",
    )
    # Per-chunk canonicalization can't collapse people ACROSS chunks: the
    # deterministic merge unions raw chunk outputs, so Russian grammatical-case and
    # ё/е variants of one person survive (Коля/Колей, Лёша/Леша). Canonicalize the
    # COMPLETE, already-clean chunk union directly — re-extracting people from the
    # reduce prose instead would re-introduce diarization speaker labels.
    merged["people_mentioned"] = await _canonicalize_people_names(
        merged["people_mentioned"], language=language
    )
    return SummaryResult(
        title=reduced.title,
        summary=reduced.summary,
        sentiment=reduced.sentiment,
        **merged,
    )


async def summarize_transcript(
    transcript: str,
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
    style: str = DEFAULT_SUMMARY_STYLE,
    instructions: str | None = None,
) -> SummaryResult:
    """Summarize a transcript via Cerebras strict structured outputs.

    Transcripts longer than ``MAP_REDUCE_CHAR_THRESHOLD`` are summarized
    map-reduce (chunk -> per-chunk summary -> merge) so a multi-hour recording
    doesn't overflow a single completion; shorter ones use one pass.
    """
    add_sentry_breadcrumb(
        category="summarizer",
        message="Summarizing transcript",
        data={"transcript_length": len(transcript), "language": language, "style": style},
    )
    if len(transcript) > MAP_REDUCE_CHAR_THRESHOLD:
        result = await _map_reduce_summarize(
            transcript, language=language, style=style, instructions=instructions
        )
    else:
        result = await _summarize_transcript_once(
            transcript, language=language, style=style, instructions=instructions
        )
    add_sentry_breadcrumb(category="summarizer", message="Summarization completed")
    return result


CONTENT_SUMMARY_INSTRUCTIONS = """\
You summarize a piece of content (a web article, PDF, note, video transcript,
email, or social post). Output one structured object that follows the provided
schema.

Rules:
- Do not invent facts. Only include information actually present in the content.
  Use null for unknown nullable fields and empty arrays for absent lists; never
  pad to look complete.
- Write the `summary` field in clear prose. For substantive content, target
  4-10 sentences; for very short content, stay short and do not pad.
- Keep proper nouns, numbers, and direct quotes verbatim. Preserve project,
  company, product, person, place, date, price, metric, and quoted wording
  exactly when the content provides it.
- Hard caps: key_points <= 15, decisions <= 20, action_items <= 30, topics <=
  20, people_mentioned <= 30, follow_up_questions <= 10, highlights <= 10.
- Keep descriptions specific: names, dates, numbers, quoted phrases.
- For people_mentioned, list each distinct person once, using their canonical
  name in the nominative case; merge grammatical cases, short forms, and
  diminutives of the same person (e.g. «Коля»/«Колей» -> «Коля»). Never list the
  same person twice.
- The top-level title and each highlight title MUST be plain text: no markdown,
  no surrounding quotes.
- action_items: only extract genuine tasks/next-steps the content implies for
  the reader; for purely informational content this may be empty.
"""


CONTENT_STYLE_INSTRUCTIONS = {
    "brief": (
        "Keep the summary to 1-2 sentences. Preserve exact names, numbers, and "
        "quoted wording while being concise."
    ),
    "medium": (
        "Write a clear 4-10 sentence prose summary for substantive content. "
        "For a short note, stay shorter and do not pad."
    ),
    "detailed": (
        "Write a thorough 4-10 sentence prose summary. Cover the full content, "
        "including important context, names, dates, numbers, quotes, and conclusions."
    ),
    "structured": (
        "Cover the content completely — every distinct point, decision, and action, "
        "with no padding. Use clear prose for the summary and structured list fields "
        "for details."
    ),
}


MEDIA_CONTENT_SUMMARY_INSTRUCTIONS = """\
Media-specific quality rules for video/audio transcripts:
- Overall overview: start with the complete source's main topic and purpose, not
  a narrow opening detail.
- Highlight crucial data: preserve important quotes, names, dates, numbers,
  metrics, examples, claims, and conclusions.
- Identify key points: cover the significant ideas and changes in direction
  across the whole transcript, not only the beginning.
- Use timestamps and section summaries when time-coded segments are available:
  make key moments concrete enough to map back to the source segment.
- Preserve the source tone, style, and language while keeping the result easy to
  skim.
"""


KEY_MOMENTS_INSTRUCTIONS = """\
Extract the key moments / main points of this content as a scannable table.

Rules:
- Return 3-15 distinct moments, most important first. Do not pad.
- ``moment``: a short plain-text label for what happens / the point made.
- ``why_it_matters``: one concise sentence on the significance.
- ``quote``: a short verbatim excerpt from the content if one captures the
  moment well, else null. Never fabricate a quote.
- ``timestamp``: ONLY when the content carries explicit time markers (e.g. a
  video/audio transcript with [MM:SS] or HH:MM:SS). Copy the marker for the
  moment. For articles, notes, or any text without timestamps, return null.
  Never invent timestamps.
- All text plain (no markdown, no surrounding quotes except inside ``quote``).
"""


def build_content_summary_prompt(
    *,
    content_kind: str = "content",
    language: str = DEFAULT_SUMMARY_LANGUAGE,
    style: str = DEFAULT_SUMMARY_STYLE,
    instructions: str | None = None,
) -> str:
    """Build the universal-content summarization prompt (instructions only)."""
    parts = [CONTENT_SUMMARY_INSTRUCTIONS]
    if content_kind and content_kind != "content":
        parts.append(f"\nThe content is a {content_kind}.")
    if _is_time_based_content_kind(content_kind):
        parts.append("\n" + MEDIA_CONTENT_SUMMARY_INSTRUCTIONS)

    style_text = CONTENT_STYLE_INSTRUCTIONS.get(
        style,
        CONTENT_STYLE_INSTRUCTIONS[DEFAULT_SUMMARY_STYLE],
    )
    parts.append(f"\nSTYLE: {style_text}")

    if language and language != DEFAULT_SUMMARY_LANGUAGE:
        parts.append(
            f"\nOUTPUT LANGUAGE: Write ALL text fields in {language}."
        )
    else:
        parts.append(
            "\nOUTPUT LANGUAGE: Write ALL text fields in the dominant language "
            "of the content (Russian content -> Russian; English -> English)."
        )

    if instructions and instructions.strip():
        parts.append(
            "\nADDITIONAL INSTRUCTIONS: "
            f"{instructions.strip()}\nApply these while preserving accuracy."
        )

    parts.append("\nContent:\n")
    return "\n".join(parts)


def _is_time_based_content_kind(content_kind: str | None) -> bool:
    kind = (content_kind or "").strip().lower()
    return any(marker in kind for marker in ("video", "audio", "podcast", "transcript"))


async def summarize_content(
    text: str,
    *,
    content_kind: str = "content",
    language: str = DEFAULT_SUMMARY_LANGUAGE,
    style: str = DEFAULT_SUMMARY_STYLE,
    instructions: str | None = None,
) -> SummaryResult:
    """Summarize any text content (article, note, transcript, ...).

    Reuses the same structured-output contract as ``summarize_transcript`` so
    items and recordings share one summary shape, but with general-content
    framing instead of meeting-specific framing.
    """
    add_sentry_breadcrumb(
        category="summarizer",
        message="Summarizing content",
        data={"content_length": len(text), "kind": content_kind, "language": language},
    )
    _require_cerebras_key()

    prompt = build_content_summary_prompt(
        content_kind=content_kind, language=language, style=style, instructions=instructions
    )
    client = get_cerebras_client()
    try:
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=_summary_messages(prompt, text),
            response_format=strict_json_response_format(
                _SummarySchema,
                name="content_summary",
            ),
            reasoning_effort="medium",
            max_completion_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Content summarization failed: {exc}") from exc

    try:
        parsed = chat_completion_parsed(
            response,
            _SummarySchema,
            operation="Content summarization",
        )
    except CerebrasResponseError as exc:
        raise SummarizationError(f"Content summarization failed: {exc}") from exc

    add_sentry_breadcrumb(category="summarizer", message="Content summarization completed")
    return SummaryResult(
        title=parsed.title,
        summary=parsed.summary,
        key_points=parsed.key_points,
        decisions=[d.model_dump() for d in parsed.decisions],
        action_items=[a.model_dump() for a in parsed.action_items],
        topics=parsed.topics,
        people_mentioned=_strip_speaker_labels(parsed.people_mentioned),
        follow_up_questions=parsed.follow_up_questions,
        sentiment=parsed.sentiment,
        highlights=[h.model_dump() for h in parsed.highlights],
    )


@dataclass
class KeyMoment:
    """One row of the key-moments table (the hero "forward → table" output)."""

    timestamp: str | None
    moment: str
    why_it_matters: str
    quote: str | None
    importance: str
    start_ms: int | None = None
    end_ms: int | None = None


async def extract_key_moments(
    text: str,
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
) -> list[KeyMoment]:
    """Extract a scannable key-moments table from any content via Cerebras.

    For time-based media whose transcript carries markers, ``timestamp`` is
    populated from those markers; for plain text it is null. Word-level
    millisecond resolution (Deepgram) is layered on by
    ``resolve_key_moment_timestamps``.
    """
    add_sentry_breadcrumb(
        category="summarizer",
        message="Extracting key moments",
        data={"content_length": len(text), "language": language},
    )
    _require_cerebras_key()

    language_instruction = (
        f"\nWrite all text in {language}."
        if language and language not in {DEFAULT_SUMMARY_LANGUAGE, "multi"}
        else "\nWrite all text in the dominant language of the content."
    )
    client = get_cerebras_client()
    try:
        prompt = KEY_MOMENTS_INSTRUCTIONS + language_instruction + "\n\nContent:\n"
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=_summary_messages(prompt, text),
            response_format=strict_json_response_format(
                _KeyMomentsSchema,
                name="key_moments",
            ),
            reasoning_effort="medium",
            max_completion_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Key moments extraction failed: {exc}") from exc

    try:
        parsed = chat_completion_parsed(
            response,
            _KeyMomentsSchema,
            operation="Key moments extraction",
        )
    except CerebrasResponseError as exc:
        raise SummarizationError(f"Key moments extraction failed: {exc}") from exc

    return [
        KeyMoment(
            timestamp=m.timestamp,
            moment=m.moment,
            why_it_matters=m.why_it_matters,
            quote=m.quote,
            importance=m.importance,
        )
        for m in parsed.moments
    ]


def resolve_key_moment_timestamps(
    moments: list[KeyMoment],
    segments: list[dict],
) -> list[KeyMoment]:
    """Attach start_ms/end_ms to moments by matching against transcript segments.

    Reuses the word-overlap heuristic from ``resolve_highlight_timestamps`` so
    a key-moments table over a recording/video jumps to the right point. Plain
    text (no segments) is returned unchanged.
    """
    if not segments:
        return moments

    def _words(value: str | None) -> set[str]:
        if not value:
            return set()
        return set(re.sub(r"[^\w\s]", " ", value.lower()).split())

    for moment in moments:
        target = _words(moment.moment) | _words(moment.quote)
        best_score = 0
        best_segment: dict | None = None
        for seg in segments:
            overlap = len(target & _words(seg.get("content")))
            if overlap > best_score:
                best_score = overlap
                best_segment = seg
        if best_segment is not None:
            moment.start_ms = best_segment.get("start_ms")
            moment.end_ms = best_segment.get("end_ms")
            if moment.timestamp is None and isinstance(moment.start_ms, int):
                moment.timestamp = _format_timestamp_ms(moment.start_ms)
    return moments


def _format_timestamp_ms(value: int) -> str:
    total_seconds = max(value // 1000, 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


TITLE_SAMPLE_MAX_CHARS = 6000


def _title_sample(transcript: str, *, max_chars: int = TITLE_SAMPLE_MAX_CHARS) -> str:
    """Representative excerpt for title generation.

    Titling on only the opening of a recording lets greetings / small-talk
    dominate (a 42-min gamification interview was titled after its opening
    weather chit-chat). For long transcripts we stitch head + middle + tail so
    the main subject is visible wherever it sits; shorter ones are used whole.
    """
    text = transcript.strip()
    if len(text) <= max_chars:
        return text
    head_len = max_chars * 5 // 12
    mid_len = max_chars * 4 // 12
    tail_len = max_chars - head_len - mid_len
    mid_start = (len(text) - mid_len) // 2
    head = text[:head_len]
    middle = text[mid_start : mid_start + mid_len]
    tail = text[len(text) - tail_len :]
    return f"{head}\n[...]\n{middle}\n[...]\n{tail}"


async def generate_title(
    transcript: str,
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
) -> str:
    """Generate a short descriptive title from transcript text via Cerebras."""
    add_sentry_breadcrumb(category="summarizer", message="Generating title")
    _require_cerebras_key()

    snippet = _title_sample(transcript)
    language_instruction = (
        f"Write the title in {language}."
        if language and language not in {DEFAULT_SUMMARY_LANGUAGE, "multi"}
        else (
            "Write the title in the dominant language of the transcript. "
            "If the transcript is primarily in Russian, output Russian. "
            "If the transcript is primarily in English, output English."
        )
    )
    client = get_cerebras_client()
    try:
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "Return only the requested plain title text.",
                },
                {
                    "role": "user",
                    "content": (
                        "Generate a short title (3-7 words) for this audio recording. "
                        "Base it on the MAIN subject or purpose of the recording. "
                        "Ignore opening greetings and small talk (weather, travel, "
                        "health, logistics, scheduling) and closing remarks — they are "
                        "not what the recording is about. The transcript below may be "
                        "excerpts taken from across the recording. Return ONLY the plain "
                        "title text — no markdown formatting (no **bold**, no *italics*, "
                        "no asterisks, no quotes, no #), nothing else. "
                        f"{language_instruction}\n\nTranscript:\n{snippet}"
                    ),
                },
            ],
            reasoning_effort="low",
            max_completion_tokens=256,
        )
        return chat_completion_text(response, operation="Title generation")
    except Exception as exc:  # noqa: BLE001
        capture_sentry_exception(exc)
        raise SummarizationError(f"Title generation failed: {exc}") from exc


def resolve_highlight_timestamps(
    highlights: list[dict],
    segments: list[dict],
) -> list[dict]:
    """Ground each highlight to its best-matching transcript segment.

    Attaches the segment's time range (start_ms/end_ms) and, when the segment
    carries an ``id``, cites it in ``source_segment_ids`` — a verifiable link back
    to the source. Highlights with no lexical match keep null timestamps and no
    citation: they are left UNGROUNDED (flagged, never dropped) so the source can
    be checked rather than silently trusted.
    """
    if not segments:
        return highlights

    def _words(text: str | None) -> set[str]:
        if not text:
            return set()
        clean = re.sub(r"[^\w\s]", " ", text.lower())
        return set(clean.split())

    resolved: list[dict] = []
    for highlight in highlights:
        hl = dict(highlight)
        hl_words = _words(hl.get("title")) | _words(hl.get("description"))

        best_score = -1
        best_segment: dict | None = None
        for seg in segments:
            seg_words = _words(seg.get("content"))
            overlap = len(hl_words & seg_words)
            if overlap > best_score:
                best_score = overlap
                best_segment = seg

        if best_segment and best_score > 0:
            hl["start_ms"] = best_segment.get("start_ms")
            hl["end_ms"] = best_segment.get("end_ms")
            seg_id = best_segment.get("id")
            if seg_id is not None:
                hl["source_segment_ids"] = [seg_id]

        resolved.append(hl)
    return resolved


ENTITY_EXTRACTION_PROMPT = """\
Extract entities from this transcript. Focus on:
- People mentioned by name. Use each person's canonical name in the nominative
  case (именительный падеж), once. Merge grammatical cases, short forms, and
  diminutives of the same person (e.g. «Коля»/«Колей» -> «Коля»; «Лёша»/«Лёш» ->
  «Лёша»). Never emit the same person as two entities.
- Projects or products discussed
- Topics and themes
- Organizations or companies

Do not invent entities not present in the transcript. If there are none of a
given type, return an empty array — do not pad.
Return at most 50 entities and at most 5 relations per entity.

Transcript:
"""


@dataclass
class EntityResult:
    """Extracted entity from transcript."""

    name: str
    type: str
    context: str
    relations: list[dict]


async def extract_entities(transcript: str) -> list[EntityResult]:
    """Extract entities from a transcript via Cerebras strict structured outputs."""
    add_sentry_breadcrumb(
        category="summarizer",
        message="Extracting entities",
        data={"transcript_length": len(transcript)},
    )
    _require_cerebras_key()

    client = get_cerebras_client()

    try:
        response = await client.chat.completions.create(
            model=settings.cerebras_llm_model,
            messages=_summary_messages(ENTITY_EXTRACTION_PROMPT, transcript),
            response_format=strict_json_response_format(
                _EntityExtractionSchema,
                name="entity_extraction",
            ),
            reasoning_effort="low",
            max_completion_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Entity extraction failed: {exc}") from exc

    try:
        parsed = chat_completion_parsed(
            response,
            _EntityExtractionSchema,
            operation="Entity extraction",
        )
    except CerebrasResponseError as exc:
        raise SummarizationError(f"Entity extraction failed: {exc}") from exc

    return [
        EntityResult(
            name=entity.name,
            type=entity.type,
            context=entity.context,
            relations=[relation.model_dump() for relation in entity.relations],
        )
        for entity in parsed.entities
    ]
