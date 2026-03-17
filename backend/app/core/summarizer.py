"""Claude API integration for summarization and entity extraction."""

import json
import logging
import re
from dataclasses import dataclass

from app.config import get_settings
from app.core.chat import _get_anthropic_client

logger = logging.getLogger(__name__)
settings = get_settings()


class SummarizationError(Exception):
    """Error during summarization."""
    pass


SUMMARY_PROMPT = """
Analyze this meeting transcript. Output ONLY valid JSON:

{
  "title": "Brief meeting title (5-10 words)",
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
      "title": "Short title of the key moment (5-15 words)",
      "description": "Brief description with context, or null",
      "speaker": "Speaker name or null",
      "importance": "high|medium|low"
    }
  ]
}

INSTRUCTIONS:
- Extract ALL action items with assigned owners if mentioned
- If information is missing, use null rather than assumptions
- Keep descriptions specific: include names, dates, numbers
- Identify speakers when possible
- For highlights, extract the most important moments: decisions made, key insights,
  important questions raised, concerns flagged, major topic shifts, and notable quotes
- Each highlight should be a distinct, meaningful moment from the conversation
- Limit highlights to the 5-10 most important moments

Transcript:
"""


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


async def summarize_transcript(transcript: str) -> SummaryResult:
    """
    Summarize a transcript using Claude API.

    Args:
        transcript: The full transcript text with speaker labels

    Returns:
        SummaryResult with extracted information
    """
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = _get_anthropic_client()

    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": SUMMARY_PROMPT + transcript,
            }
        ],
    )

    # Extract JSON from response
    response_text = message.content[0].text

    # Find JSON in response (handle markdown code blocks)
    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        json_str = response_text[start:end if end != -1 else len(response_text)].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        json_str = response_text[start:end if end != -1 else len(response_text)].strip()
    else:
        json_str = response_text.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.debug(f"Response was: {response_text[:500]}")
        raise SummarizationError(f"Invalid JSON response from Claude: {e}") from e

    return SummaryResult(
        title=data.get("title", "Untitled"),
        summary=data.get("summary", ""),
        key_points=data.get("key_points", []),
        decisions=data.get("decisions", []),
        action_items=data.get("action_items", []),
        topics=data.get("topics", []),
        people_mentioned=data.get("people_mentioned", []),
        follow_up_questions=data.get("follow_up_questions", []),
        sentiment=data.get("sentiment", "neutral"),
        highlights=data.get("highlights", []),
    )


async def generate_title(transcript: str) -> str:
    """Generate a short descriptive title from transcript text using Claude."""
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    # Use first ~500 chars of transcript for speed
    snippet = transcript[:500]

    client = _get_anthropic_client()
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=50,
        messages=[
            {
                "role": "user",
                "content": (
                    "Generate a short title (3-7 words) for this audio recording based on "
                    "its transcript. Return ONLY the title text, nothing else.\n\n"
                    f"Transcript:\n{snippet}"
                ),
            }
        ],
    )
    title = message.content[0].text.strip().strip('"').strip("'")
    # Truncate if model returned something too long
    if len(title) > 100:
        title = title[:97] + "..."
    return title


def resolve_highlight_timestamps(
    highlights: list[dict],
    segments: list[dict],
) -> list[dict]:
    """Map each highlight to the best-matching segment's time range.

    Uses simple word-overlap scoring between the highlight text (title +
    description) and each segment's content.  The highlight dict is
    returned with ``start_ms`` and ``end_ms`` populated from the
    best-matching segment.

    Args:
        highlights: List of highlight dicts from Claude.
        segments: List of dicts with ``content``, ``start_ms``, ``end_ms``.

    Returns:
        A new list of highlight dicts with timestamps resolved.
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
        # Build a bag of words from the highlight's title and description
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
    """
    Extract entities from a transcript using Claude API.

    Args:
        transcript: The full transcript text

    Returns:
        List of extracted entities
    """
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = _get_anthropic_client()

    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": ENTITY_EXTRACTION_PROMPT + transcript,
            }
        ],
    )

    response_text = message.content[0].text

    # Find JSON in response
    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        json_str = response_text[start:end if end != -1 else len(response_text)].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        json_str = response_text[start:end if end != -1 else len(response_text)].strip()
    else:
        json_str = response_text.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude entity response as JSON: {e}")
        logger.debug(f"Response was: {response_text[:500]}")
        raise SummarizationError(f"Invalid JSON response from Claude: {e}") from e

    return [
        EntityResult(
            name=e.get("name", ""),
            type=e.get("type", "topic"),
            context=e.get("context", ""),
            relations=e.get("relations", []),
        )
        for e in data.get("entities", [])
    ]
