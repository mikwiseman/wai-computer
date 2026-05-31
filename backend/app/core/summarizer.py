"""OpenAI Responses API summarization, title generation, and entity extraction.

Uses gpt-5.5 structured outputs via ``client.responses.parse(text_format=...)`` so
the model is guaranteed to emit a JSON shape that matches our Pydantic schemas.
That removes the defensive ``json.loads`` + ``SummarizationError`` path the
previous implementation needed, and makes downstream code free to trust the
shape it receives.
"""

import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_exception,
)
from app.core.openai_client import get_openai_client
from app.core.openai_responses import (
    OpenAIResponseError,
    ensure_response_completed,
    response_output_text,
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
# Prompts. The structured-output schema is enforced by ``text_format``, so the
# prompt itself only carries instructions (no JSON shape to repeat).
# ---------------------------------------------------------------------------


SUMMARY_INSTRUCTIONS = """\
You summarize a meeting transcript. Output one structured object that follows the
provided schema.

Rules:
- Do not invent facts. Only include information that is actually present in the
  transcript. If a field is unknown, return null for nullable fields or an empty
  array for lists. Do not pad lists to look complete.
- Hard caps: key_points <= 15, decisions <= 20, action_items <= 30, topics <=
  20, people_mentioned <= 30, follow_up_questions <= 10, highlights <= 10.
- Keep descriptions specific: include names, dates, numbers, and quoted phrases
  when the transcript provides them.
- Identify speakers when possible; leave the speaker null when it is unclear.
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
}

DEFAULT_SUMMARY_LANGUAGE = "auto"
DEFAULT_SUMMARY_STYLE = "medium"


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


async def summarize_transcript(
    transcript: str,
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
    style: str = DEFAULT_SUMMARY_STYLE,
    instructions: str | None = None,
) -> SummaryResult:
    """Summarize a transcript via the OpenAI Responses API with structured outputs."""
    add_sentry_breadcrumb(
        category="summarizer",
        message="Summarizing transcript",
        data={"transcript_length": len(transcript), "language": language, "style": style},
    )
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    prompt = build_summary_prompt(language=language, style=style, instructions=instructions)
    client = get_openai_client()

    try:
        response = await client.responses.parse(
            model=settings.openai_llm_model,
            input=prompt + transcript,
            text_format=_SummarySchema,
            reasoning={"effort": "medium"},
            max_output_tokens=4096,
        )
        ensure_response_completed(response, operation="Summarization")
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Summarization failed: {exc}") from exc

    parsed = response.output_parsed
    if parsed is None:
        raise SummarizationError("OpenAI returned no parsed summary payload")

    add_sentry_breadcrumb(category="summarizer", message="Summarization completed")

    return SummaryResult(
        title=parsed.title,
        summary=parsed.summary,
        key_points=parsed.key_points,
        decisions=[d.model_dump() for d in parsed.decisions],
        action_items=[a.model_dump() for a in parsed.action_items],
        topics=parsed.topics,
        people_mentioned=parsed.people_mentioned,
        follow_up_questions=parsed.follow_up_questions,
        sentiment=parsed.sentiment,
        highlights=[h.model_dump() for h in parsed.highlights],
    )


CONTENT_SUMMARY_INSTRUCTIONS = """\
You summarize a piece of content (a web article, PDF, note, video transcript,
email, or social post). Output one structured object that follows the provided
schema.

Rules:
- Do not invent facts. Only include information actually present in the content.
  Use null for unknown nullable fields and empty arrays for absent lists; never
  pad to look complete.
- Hard caps: key_points <= 15, decisions <= 20, action_items <= 30, topics <=
  20, people_mentioned <= 30, follow_up_questions <= 10, highlights <= 10.
- Keep descriptions specific: names, dates, numbers, quoted phrases.
- The top-level title and each highlight title MUST be plain text: no markdown,
  no surrounding quotes.
- action_items: only extract genuine tasks/next-steps the content implies for
  the reader; for purely informational content this may be empty.
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

    style_text = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS[DEFAULT_SUMMARY_STYLE])
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
        parts.append(f"\nADDITIONAL INSTRUCTIONS: {instructions.strip()}")

    parts.append("\nContent:\n")
    return "\n".join(parts)


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
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    prompt = build_content_summary_prompt(
        content_kind=content_kind, language=language, style=style, instructions=instructions
    )
    client = get_openai_client()
    try:
        response = await client.responses.parse(
            model=settings.openai_llm_model,
            input=prompt + text,
            text_format=_SummarySchema,
            reasoning={"effort": "medium"},
            max_output_tokens=4096,
        )
        ensure_response_completed(response, operation="Content summarization")
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Content summarization failed: {exc}") from exc

    parsed = response.output_parsed
    if parsed is None:
        raise SummarizationError("OpenAI returned no parsed summary payload")

    add_sentry_breadcrumb(category="summarizer", message="Content summarization completed")
    return SummaryResult(
        title=parsed.title,
        summary=parsed.summary,
        key_points=parsed.key_points,
        decisions=[d.model_dump() for d in parsed.decisions],
        action_items=[a.model_dump() for a in parsed.action_items],
        topics=parsed.topics,
        people_mentioned=parsed.people_mentioned,
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
    """Extract a scannable key-moments table from any content via OpenAI.

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
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    language_instruction = (
        f"\nWrite all text in {language}."
        if language and language not in {DEFAULT_SUMMARY_LANGUAGE, "multi"}
        else "\nWrite all text in the dominant language of the content."
    )
    client = get_openai_client()
    try:
        response = await client.responses.parse(
            model=settings.openai_llm_model,
            input=KEY_MOMENTS_INSTRUCTIONS + language_instruction + "\n\nContent:\n" + text,
            text_format=_KeyMomentsSchema,
            reasoning={"effort": "medium"},
            max_output_tokens=4096,
        )
        ensure_response_completed(response, operation="Key moments extraction")
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Key moments extraction failed: {exc}") from exc

    parsed = response.output_parsed
    if parsed is None:
        raise SummarizationError("OpenAI returned no parsed key-moments payload")

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
    return moments


async def generate_title(
    transcript: str,
    *,
    language: str = DEFAULT_SUMMARY_LANGUAGE,
) -> str:
    """Generate a short descriptive title from transcript text via OpenAI."""
    add_sentry_breadcrumb(category="summarizer", message="Generating title")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    snippet = transcript[:500]
    language_instruction = (
        f"Write the title in {language}."
        if language and language not in {DEFAULT_SUMMARY_LANGUAGE, "multi"}
        else (
            "Write the title in the dominant language of the transcript. "
            "If the transcript is primarily in Russian, output Russian. "
            "If the transcript is primarily in English, output English."
        )
    )
    client = get_openai_client()
    response = await client.responses.create(
        model=settings.openai_llm_model,
        input=(
            "Generate a short title (3-7 words) for this audio recording based on "
            "its transcript. Return ONLY the plain title text — no markdown "
            "formatting (no **bold**, no *italics*, no asterisks, no quotes, no #), "
            f"nothing else. {language_instruction}\n\n"
            f"Transcript:\n{snippet}"
        ),
        reasoning={"effort": "low"},
        max_output_tokens=256,
    )
    try:
        ensure_response_completed(response, operation="Title generation")
        return response_output_text(response)
    except OpenAIResponseError as exc:
        capture_sentry_exception(exc)
        raise SummarizationError(f"Title generation failed: {exc}") from exc


def resolve_highlight_timestamps(
    highlights: list[dict],
    segments: list[dict],
) -> list[dict]:
    """Map each highlight to the best-matching segment's time range."""
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

        resolved.append(hl)
    return resolved


ENTITY_EXTRACTION_PROMPT = """\
Extract entities from this transcript. Focus on:
- People mentioned by name
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
    """Extract entities from a transcript via OpenAI with structured outputs."""
    add_sentry_breadcrumb(
        category="summarizer",
        message="Extracting entities",
        data={"transcript_length": len(transcript)},
    )
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = get_openai_client()

    try:
        response = await client.responses.parse(
            model=settings.openai_llm_model,
            input=ENTITY_EXTRACTION_PROMPT + transcript,
            text_format=_EntityExtractionSchema,
            reasoning={"effort": "low"},
            max_output_tokens=4096,
        )
        ensure_response_completed(response, operation="Entity extraction")
    except Exception as exc:  # noqa: BLE001 — capture for breadcrumbs then re-raise
        capture_sentry_exception(exc)
        raise SummarizationError(f"Entity extraction failed: {exc}") from exc

    parsed = response.output_parsed
    if parsed is None:
        raise SummarizationError("OpenAI returned no parsed entity payload")

    return [
        EntityResult(
            name=entity.name,
            type=entity.type,
            context=entity.context,
            relations=[relation.model_dump() for relation in entity.relations],
        )
        for entity in parsed.entities
    ]
