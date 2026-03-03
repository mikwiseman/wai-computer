"""Claude API integration for summarization and entity extraction."""

import json
import logging
from dataclasses import dataclass

import anthropic

from app.config import get_settings

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
  "sentiment": "positive|neutral|negative|mixed"
}

INSTRUCTIONS:
- Extract ALL action items with assigned owners if mentioned
- If information is missing, use null rather than assumptions
- Keep descriptions specific: include names, dates, numbers
- Identify speakers when possible

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

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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
    )


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

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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
