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

from pydantic import BaseModel

from app.config import get_settings
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_exception,
)
from app.core.openai_client import get_openai_client

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
    key_points: list[str]
    decisions: list[_Decision]
    action_items: list[_ActionItem]
    topics: list[str]
    people_mentioned: list[str]
    follow_up_questions: list[str]
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    highlights: list[_Highlight]


class _EntityRelation(BaseModel):
    related_to: str
    relation_type: Literal["works_on", "mentioned_with", "related_to"]


class _Entity(BaseModel):
    name: str
    type: Literal["person", "topic", "project", "organization"]
    context: str
    relations: list[_EntityRelation]


class _EntityExtractionSchema(BaseModel):
    entities: list[_Entity]


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


async def generate_title(transcript: str) -> str:
    """Generate a short descriptive title from transcript text via OpenAI."""
    add_sentry_breadcrumb(category="summarizer", message="Generating title")
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    snippet = transcript[:500]
    client = get_openai_client()
    response = await client.responses.create(
        model=settings.openai_llm_model,
        input=(
            "Generate a short title (3-7 words) for this audio recording based on "
            "its transcript. Return ONLY the plain title text — no markdown "
            "formatting (no **bold**, no *italics*, no asterisks, no quotes, no #), "
            "nothing else.\n\n"
            f"Transcript:\n{snippet}"
        ),
        reasoning={"effort": "low"},
        max_output_tokens=50,
    )
    return response.output_text.strip()


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
