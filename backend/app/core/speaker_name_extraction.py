"""LLM-based name introduction parsing.

After ElevenLabs returns a diarized transcript, ask an LLM to identify which
speaker cluster corresponds to which real name based on direct introductions
("this is John", "I'm Alice") and unambiguous addressing ("Sarah, can you...").

Only ``high``-confidence assignments are applied to Person records. Anything
ambiguous is dropped on purpose - we'd rather miss a name than mislabel a
speaker who was only mentioned in passing.

The applied output mutates the per-recording speaker_assignments mapping
returned by ``identify_speakers_for_recording``, so the same Segment-writing
loop in the audio processing pipeline gets the right person_id.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.openai_client import get_openai_client
from app.core.openai_responses import ensure_response_completed
from app.models.person import Person

if TYPE_CHECKING:
    from app.core.transcript_utils import TranscriptResult

logger = logging.getLogger(__name__)

# Cap input we send to the LLM. Names almost always show up in the first few
# minutes of a conversation, and a long transcript inflates cost without
# improving extraction quality.
_TRANSCRIPT_CHAR_BUDGET = 8000

# Reject suspiciously long "names". Real human names rarely exceed 80 chars
# even with multiple given/family parts, and a long string is usually the
# model echoing a phrase instead of a name.
_MAX_EXTRACTED_NAME_CHARS = 80


class _NameAssignment(BaseModel):
    speaker: str = Field(description="The speaker cluster label exactly as shown, e.g. 'speaker_0'.")
    name: str = Field(description="Real name as introduced.")
    confidence: Literal["high", "medium", "low"]
    evidence: str = Field(description="The transcript phrase that justifies this assignment.")


class _NameExtractionSchema(BaseModel):
    assignments: list[_NameAssignment] = Field(max_length=20)


_EXTRACTION_INSTRUCTIONS = """\
You analyse a diarised meeting transcript. Each line begins with a speaker
cluster label like [speaker_0], [speaker_1]. Identify which cluster
corresponds to which real human name.

Output an assignment ONLY for these high-confidence cases:
- A speaker introduces themselves with phrases like:
  "this is John", "I'm Alice", "my name is Bob", "Mike speaking",
  "это Михаил", "меня зовут Анна".
- Someone addresses one specific speaker BY NAME and that speaker then
  responds: "Sarah, what about you?" -> Sarah's next turn = Sarah.
- A speaker handover: "back to you, Mike" / "Mike, your turn".

DO NOT output an assignment when:
- A name is mentioned in third person ("John said...", "I talked to Mary").
- The name is a generic address with no specific target ("Hey everyone").
- You are not sure which cluster the name refers to.

For "confidence": use "high" only for direct self-introductions or the
clearest addressed-then-responded pattern. Use "medium" for plausible but
uncertain. Anything else, omit entirely.

For "evidence": include the short transcript phrase (one sentence) that
justifies the assignment. Quote the actual text.
"""


@dataclass(frozen=True)
class AppliedName:
    """An applied name assignment for downstream logging / breadcrumbs."""

    raw_label: str
    person_id: uuid.UUID
    name: str
    created_person: bool
    aliased_existing: bool


async def extract_speaker_names(
    *,
    transcript_results: list["TranscriptResult"],
    raw_labels: Iterable[str],
) -> dict[str, _NameAssignment]:
    """Ask the LLM which raw_label corresponds to which name.

    Returns only ``high``-confidence assignments. The caller decides whether
    to apply them (create / alias Person records).
    """
    raw_labels_set = {label for label in raw_labels if label}
    if not raw_labels_set:
        return {}

    settings = get_settings()
    if not settings.openai_api_key:
        logger.info("speaker name extraction skipped: OPENAI_API_KEY not set")
        return {}

    transcript_text = _format_transcript(transcript_results)
    if not transcript_text:
        return {}

    client = get_openai_client()
    try:
        response = await client.responses.parse(
            model=settings.openai_llm_model,
            input=_EXTRACTION_INSTRUCTIONS + "\n\nTranscript:\n" + transcript_text,
            text_format=_NameExtractionSchema,
            reasoning={"effort": "low"},
            max_output_tokens=512,
        )
        ensure_response_completed(response, operation="Speaker name extraction")
    except Exception as exc:  # noqa: BLE001 -- name extraction is best-effort
        logger.warning("speaker name extraction failed: %s", exc)
        return {}

    parsed = response.output_parsed
    if parsed is None:
        return {}

    high_confidence: dict[str, _NameAssignment] = {}
    for assignment in parsed.assignments:
        if assignment.confidence != "high":
            continue
        speaker = assignment.speaker.strip()
        if speaker not in raw_labels_set:
            # Model invented a cluster label not present in the transcript.
            continue
        cleaned_name = _clean_name(assignment.name)
        if cleaned_name is None:
            continue
        # If the model gave multiple assignments for the same cluster, keep
        # the first - it's an ordered list and the first hit is usually the
        # most direct introduction.
        if speaker in high_confidence:
            continue
        high_confidence[speaker] = _NameAssignment(
            speaker=speaker,
            name=cleaned_name,
            confidence="high",
            evidence=assignment.evidence,
        )

    return high_confidence


async def apply_extracted_names(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    speaker_assignments: dict[str, tuple[uuid.UUID, float] | None],
    extracted: dict[str, _NameAssignment],
) -> list[AppliedName]:
    """Resolve extracted names against the user's Person address book.

    Mutates ``speaker_assignments`` in place so the Segment-writing loop
    afterwards picks up the new person_id. Returns the list of applied
    changes for downstream telemetry.
    """
    if not extracted:
        return []

    applied: list[AppliedName] = []

    for raw_label, assignment in extracted.items():
        existing = await _find_person_by_name(
            db=db, user_id=user_id, name=assignment.name
        )

        current = speaker_assignments.get(raw_label)
        current_person_id = current[0] if current is not None else None

        if existing is not None:
            if current_person_id == existing.id:
                # Voice ID already matched correctly - nothing to do.
                continue
            speaker_assignments[raw_label] = (existing.id, 1.0)
            applied.append(
                AppliedName(
                    raw_label=raw_label,
                    person_id=existing.id,
                    name=existing.display_name,
                    created_person=False,
                    aliased_existing=False,
                )
            )
            continue

        if current_person_id is not None:
            # The cluster is voice-matched to someone else. Record the
            # extracted name as an alias on that Person rather than create
            # a duplicate - voice match is the stronger signal.
            target = await db.get(Person, current_person_id)
            if target is None:
                continue
            aliases = list(target.aliases or [])
            if not _alias_present(aliases, assignment.name) and target.display_name.strip().lower() != assignment.name.strip().lower():
                aliases.append(assignment.name)
                target.aliases = aliases
                await db.flush()
            applied.append(
                AppliedName(
                    raw_label=raw_label,
                    person_id=target.id,
                    name=assignment.name,
                    created_person=False,
                    aliased_existing=True,
                )
            )
            continue

        # Cluster unmatched, no existing Person with that name -> create one.
        new_person = Person(user_id=user_id, display_name=assignment.name)
        db.add(new_person)
        await db.flush()
        speaker_assignments[raw_label] = (new_person.id, 1.0)
        applied.append(
            AppliedName(
                raw_label=raw_label,
                person_id=new_person.id,
                name=new_person.display_name,
                created_person=True,
                aliased_existing=False,
            )
        )

    return applied


def _format_transcript(results: list["TranscriptResult"]) -> str:
    lines: list[str] = []
    for result in results:
        speaker = result.speaker or "speaker_unknown"
        text = (result.text or "").strip()
        if not text:
            continue
        lines.append(f"[{speaker}] {text}")
        joined = "\n".join(lines)
        if len(joined) >= _TRANSCRIPT_CHAR_BUDGET:
            return joined[:_TRANSCRIPT_CHAR_BUDGET]
    return "\n".join(lines)


def _clean_name(raw: str) -> str | None:
    name = (raw or "").strip().strip(".,!?:;\"'")
    if not name:
        return None
    if len(name) > _MAX_EXTRACTED_NAME_CHARS:
        return None
    return name


async def _find_person_by_name(
    *, db: AsyncSession, user_id: uuid.UUID, name: str
) -> Person | None:
    """Find a Person owned by user matching ``name`` against display_name or aliases."""
    needle = name.strip().lower()
    if not needle:
        return None
    # display_name exact match (case-insensitive).
    result = await db.execute(
        select(Person).where(
            Person.user_id == user_id,
            func.lower(Person.display_name) == needle,
        )
    )
    person = result.scalar_one_or_none()
    if person is not None:
        return person
    # Alias fallback - scan rows that have any aliases. Aliases are typically
    # a handful of entries so this is cheap even without a JSONB index.
    result = await db.execute(
        select(Person).where(
            Person.user_id == user_id,
            Person.aliases.isnot(None),
        )
    )
    for candidate in result.scalars():
        if _alias_present(candidate.aliases or [], name):
            return candidate
    return None


def _alias_present(aliases: list, name: str) -> bool:
    needle = name.strip().lower()
    return any(
        isinstance(alias, str) and alias.strip().lower() == needle
        for alias in aliases
    )
