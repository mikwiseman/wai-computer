"""User personalization terminology helpers."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dictation import DictationDictionaryWord
from app.models.entity import Entity
from app.models.personalization import PersonalizationImportJob, PersonalizationTerm

TERM_STATUS_VALUES = {"active", "candidate", "rejected"}
TERM_SOURCE_VALUES = {"manual", "import"}
IMPORT_SOURCE_TYPES = {"text", "file"}
MAX_IMPORT_TEXT_CHARS = 500_000

_TERM_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9_.-]{2,}")
_MULTISPACE_RE = re.compile(r"\s+")
_STRIP_CHARS = " \t\r\n\"'“”‘’.,:;!?()[]{}<>"
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "because",
    "before",
    "between",
    "could",
    "from",
    "have",
    "into",
    "need",
    "should",
    "that",
    "their",
    "there",
    "this",
    "through",
    "with",
    "would",
    "для",
    "или",
    "как",
    "надо",
    "нужно",
    "они",
    "при",
    "так",
    "там",
    "тебя",
    "тем",
    "тогда",
    "тоже",
    "только",
    "что",
    "чтобы",
    "это",
}


@dataclass(frozen=True)
class TermCandidate:
    term: str
    frequency: int


def clean_term(term: str) -> str:
    cleaned = _MULTISPACE_RE.sub(" ", term.strip(_STRIP_CHARS))
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip()
    return cleaned


def normalize_term(term: str) -> str:
    return clean_term(term).casefold()


def extract_candidate_terms(text: str, *, limit: int = 80) -> list[TermCandidate]:
    """Extract likely terminology from plain text for explicit user review."""
    observed: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for match in _TERM_RE.finditer(text):
        term = clean_term(match.group(0))
        normalized = normalize_term(term)
        if not term or len(normalized) < 4 or normalized in _STOPWORDS:
            continue
        observed.setdefault(normalized, term)
        counts[normalized] += 1

    candidates = [
        TermCandidate(term=observed[normalized], frequency=frequency)
        for normalized, frequency in counts.items()
    ]
    candidates.sort(key=lambda candidate: (-candidate.frequency, candidate.term.casefold()))
    return candidates[:limit]


def sanitize_keyterms(
    terms: list[str],
    *,
    max_terms: int,
    max_chars: int,
    max_words: int | None = None,
    token_budget: int | None = None,
) -> list[str]:
    sanitized: list[str] = []
    seen: set[str] = set()
    used_budget = 0
    for raw_term in terms:
        term = clean_term(raw_term)
        if len(term) > max_chars:
            term = term[:max_chars].rstrip()
        normalized = normalize_term(term)
        if not term or normalized in seen:
            continue
        if max_words is not None and len(term.split()) > max_words:
            continue
        if token_budget is not None:
            term_budget = len(term.split())
            if used_budget + term_budget > token_budget:
                continue
            used_budget += term_budget
        seen.add(normalized)
        sanitized.append(term)
        if len(sanitized) >= max_terms:
            break
    return sanitized


async def load_user_keyterms(
    db: AsyncSession,
    *,
    user_id: UUID,
    purpose: str,
) -> list[str]:
    """Load active terms for provider STT keyterm hints."""
    del purpose
    terms_result = await db.execute(
        select(PersonalizationTerm)
        .where(
            PersonalizationTerm.user_id == user_id,
            PersonalizationTerm.status == "active",
        )
        .order_by(PersonalizationTerm.frequency.desc(), PersonalizationTerm.updated_at.desc())
    )
    raw_terms: list[str] = []
    for term in terms_result.scalars():
        raw_terms.append(term.term)
        if term.replacement:
            raw_terms.append(term.replacement)

    dictionary_result = await db.execute(
        select(DictationDictionaryWord)
        .where(DictationDictionaryWord.user_id == user_id)
        .order_by(DictationDictionaryWord.updated_at.desc())
    )
    for word in dictionary_result.scalars():
        raw_terms.append(word.word)
        if word.replacement:
            raw_terms.append(word.replacement)

    return sanitize_keyterms(raw_terms, max_terms=250, max_chars=100, max_words=8, token_budget=900)


async def load_user_entity_terms(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 60,
) -> list[str]:
    """Recent person/project/organization names from the user's entity graph.

    Widens the summary glossary so the summarizer can canonicalize close or
    mis-transcribed proper nouns against names the user already uses.
    """
    result = await db.execute(
        select(Entity.name)
        .where(
            Entity.user_id == user_id,
            Entity.type.in_(("person", "project", "organization")),
        )
        .order_by(Entity.updated_at.desc())
        .limit(limit)
    )
    return [name.strip() for name in result.scalars().all() if name and name.strip()]


def _merge_glossary(*term_lists: list[str], cap: int = 80) -> list[str]:
    """Case-insensitive merge of term lists preserving first-seen order, capped."""
    seen: set[str] = set()
    merged: list[str] = []
    for terms in term_lists:
        for term in terms:
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(term)
            if len(merged) >= cap:
                return merged
    return merged


async def summary_personalization_instructions(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> str | None:
    approved = await load_user_keyterms(db, user_id=user_id, purpose="summary")
    entities = await load_user_entity_terms(db, user_id=user_id)
    glossary = _merge_glossary(approved, entities, cap=80)
    if not glossary:
        return None
    listed_terms = "\n".join(f"- {term}" for term in glossary)
    return (
        "Known names and terms the user already uses (people, projects, products, "
        "organizations). When a word in the transcript is clearly the same name as "
        "one of these — including an obvious transcription error or close phonetic "
        "match — use this known spelling instead. Never introduce a term that has "
        "no support in the transcript, and never invent a name.\n\n"
        f"Known terms:\n{listed_terms}"
    )


async def process_personalization_import(
    db: AsyncSession,
    *,
    job: PersonalizationImportJob,
) -> PersonalizationImportJob:
    """Extract candidates now and clear imported source text after processing."""
    job.status = "running"
    text = job.source_text or ""
    candidates = extract_candidate_terms(text)
    created_count = 0
    for candidate in candidates:
        normalized = normalize_term(candidate.term)
        existing_result = await db.execute(
            select(PersonalizationTerm).where(
                PersonalizationTerm.user_id == job.user_id,
                PersonalizationTerm.normalized_term == normalized,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            if existing.status == "candidate":
                existing.frequency = max(existing.frequency, candidate.frequency)
                existing.import_job_id = job.id
            continue
        db.add(
            PersonalizationTerm(
                user_id=job.user_id,
                import_job_id=job.id,
                term=candidate.term,
                normalized_term=normalized,
                source="import",
                status="candidate",
                frequency=candidate.frequency,
            )
        )
        created_count += 1

    job.candidate_count = created_count
    job.source_text = None
    job.status = "succeeded"
    return job
