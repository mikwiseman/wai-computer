"""User personalization terminology helpers."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dictation import DictationDictionaryWord
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


async def summary_personalization_instructions(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> str | None:
    terms = await load_user_keyterms(db, user_id=user_id, purpose="summary")
    if not terms:
        return None
    listed_terms = "\n".join(f"- {term}" for term in terms[:80])
    return (
        "Use the user's approved terminology when it appears in the transcript. "
        "Do not add terms that are not supported by the transcript.\n\n"
        f"Approved terminology:\n{listed_terms}"
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
