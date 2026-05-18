"""OpenAI Responses API summarization, title generation, and entity extraction."""

import json
import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.core.observability import (
    add_sentry_breadcrumb,
    capture_sentry_exception,
    safe_text_digest,
)
from app.core.openai_client import get_openai_client

logger = logging.getLogger(__name__)
settings = get_settings()


class SummarizationError(Exception):
    """Error during summarization."""

    pass


SUMMARY_JSON_SCHEMA = """{
  "title": "Brief meeting title (5-10 words, plain text only)",
  "summary": "2-3 sentence summary of the meeting",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "decisions": [
    {"decision": "...", "context": "..."}
  ],
  "action_items": [
    {"task": "...", "owner": "name or null",
     "due": "YYYY-MM-DD or null", "priority": "high|medium|low"}
  ],
  "topics": ["Topic 1", "Topic 2"],
  "people_mentioned": ["Name 1", "Name 2"],
  "follow_up_questions": ["Question 1"],
  "sentiment": "positive|neutral|negative|mixed",
  "highlights": [
    {
      "category": "decision|insight|question|concern|topic_shift|quote",
      "title": "Short title of the key moment (5-15 words, plain text only)",
      "description": "Brief description with context, or null",
      "speaker": "Speaker name or null",
      "importance": "high|medium|low"
    }
  ]
}"""

SUMMARY_INSTRUCTIONS = """
- Extract ALL action items with assigned owners if mentioned
- If information is missing, use null rather than assumptions
- Keep descriptions specific: include names, dates, numbers
- Identify speakers when possible
- For highlights, extract the most important moments: decisions made, key insights,
  important questions raised, concerns flagged, major topic shifts, and notable quotes
- Each highlight should be a distinct, meaningful moment from the conversation
- Limit highlights to the 5-10 most important moments
- Titles (the top-level `title` and each highlight `title`) MUST be plain text:
  no markdown formatting (no **bold**, no *italics*, no _underscores_,
  no `code`, no # headings), no surrounding quotes. Just the words."""


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
    """Build the summarization prompt with user preferences."""
    parts = ["Analyze this meeting transcript. Output ONLY valid JSON:\n"]
    parts.append(SUMMARY_JSON_SCHEMA)
    parts.append("\nINSTRUCTIONS:")
    parts.append(SUMMARY_INSTRUCTIONS)

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
    """Summarize a transcript via the OpenAI Responses API."""
    add_sentry_breadcrumb(
        category="summarizer",
        message="Summarizing transcript",
        data={"transcript_length": len(transcript), "language": language, "style": style},
    )
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    prompt = build_summary_prompt(language=language, style=style, instructions=instructions)
    client = get_openai_client()

    response = await client.responses.create(
        model=settings.openai_llm_model,
        input=prompt + transcript,
        max_output_tokens=4096,
    )
    response_text = response.output_text

    try:
        data = json.loads(response_text.strip())
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse model response as JSON: {e}")
        logger.debug(
            "Model response digest=%s",
            safe_text_digest(response_text, label="openai_response"),
        )
        capture_sentry_exception(e, extras={"response_text": response_text})
        raise SummarizationError(f"Invalid JSON response from model: {e}") from e

    add_sentry_breadcrumb(category="summarizer", message="Summarization completed")

    return SummaryResult(
        title=data["title"],
        summary=data["summary"],
        key_points=data.get("key_points", []),
        decisions=data.get("decisions", []),
        action_items=data.get("action_items", []),
        topics=data.get("topics", []),
        people_mentioned=data.get("people_mentioned", []),
        follow_up_questions=data.get("follow_up_questions", []),
        sentiment=data["sentiment"],
        highlights=data.get("highlights", []),
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


ENTITY_EXTRACTION_PROMPT = """
Extract entities from this transcript. Output ONLY valid JSON:

{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|topic|project|organization",
      "context": "Brief context of how they were mentioned",
      "relations": [
        {"related_to": "Other Entity", "relation_type": "works_on|mentioned_with|related_to"}
      ]
    }
  ]
}

Focus on:
- People mentioned by name
- Projects or products discussed
- Topics and themes
- Organizations or companies

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
    """Extract entities from a transcript via OpenAI."""
    add_sentry_breadcrumb(
        category="summarizer",
        message="Extracting entities",
        data={"transcript_length": len(transcript)},
    )
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = get_openai_client()

    response = await client.responses.create(
        model=settings.openai_llm_model,
        input=ENTITY_EXTRACTION_PROMPT + transcript,
        max_output_tokens=4096,
    )
    response_text = response.output_text

    try:
        data = json.loads(response_text.strip())
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse model entity response as JSON: {e}")
        logger.debug(
            "Model entity response digest=%s",
            safe_text_digest(response_text, label="openai_entities"),
        )
        capture_sentry_exception(e, extras={"response_text": response_text})
        raise SummarizationError(f"Invalid JSON response from model: {e}") from e

    return [
        EntityResult(
            name=e["name"],
            type=e["type"],
            context=e["context"],
            relations=e.get("relations", []),
        )
        for e in data.get("entities", [])
    ]
