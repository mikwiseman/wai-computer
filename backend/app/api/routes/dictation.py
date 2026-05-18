"""Dictation routes: AI text cleanup + persistent history/dictionary store.

Two concerns share this module:
- POST /cleanup runs the OpenAI Responses API to polish dictated text.
- /entries and /dictionary back the macOS client's local stores so they
  survive logout/login and sync across Macs.
"""

import logging
from datetime import datetime
from uuid import UUID

import openai
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.openai_client import get_openai_client
from app.core.openai_responses import (
    OpenAIResponseError,
    ensure_response_completed,
    response_output_text,
)
from app.core.transcription_options import validate_option
from app.models.dictation import DictationDictionaryWord, DictationEntry

router = APIRouter(prefix="/dictation", tags=["dictation"])
logger = logging.getLogger(__name__)
MAX_CLEANUP_TEXT_LENGTH = 100_000
MAX_CLEANUP_VOCABULARY_ENTRIES = 200
MAX_CLEANUP_VOCABULARY_ENTRY_CHARS = 60

DICTATION_CLEANUP_INSTRUCTIONS = """\
Lightly clean up dictated text.

Rules:
- Remove filler sounds and filler words in Russian and English, including э,
  эээ, э-э-э, а, ааа, а-а-а, ну, вот, типа, как бы, значит, um, uh, like,
  you know, I mean, basically, actually, so, and well.
- Remove repeated filler-only loops such as "и, э-э-э, и, э-э-э".
- Remove false starts and self-corrections while keeping the final intended
  version, for example "мы х-- мы предлагаем" becomes "мы предлагаем".
- Fix only obvious grammar, capitalization, punctuation, and paragraph breaks.
- Preserve the original language, meaning, tone, style, terminology, names,
  claims, and sentence order.
- Do not summarize, add information, change the meaning, or make the text more
  formal unless it is clearly formal already.
- Output only the cleaned text.
"""


class CleanupRequest(BaseModel):
    """Request to clean up dictated text."""

    text: str = Field(max_length=MAX_CLEANUP_TEXT_LENGTH)
    vocabulary: list[str] | None = Field(default=None)


class CleanupResponse(BaseModel):
    """Response with cleaned text."""

    text: str


def _build_vocabulary_block(vocabulary: list[str] | None) -> str:
    """Render the user's dictionary as a tagged preserve block.

    Vocabulary that must survive the cleanup pass goes inside an explicit
    XML-style tag rather than inline prose — the model treats tagged content
    as structured, not as suggestion. Caps avoid pathological lists drowning
    out the cleanup instructions.
    """
    if not vocabulary:
        return ""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in vocabulary:
        term = raw.strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(term[:MAX_CLEANUP_VOCABULARY_ENTRY_CHARS])
        if len(cleaned) >= MAX_CLEANUP_VOCABULARY_ENTRIES:
            break
    if not cleaned:
        return ""
    joined = "\n".join(cleaned)
    return (
        "\n\nThe user maintains a dictionary of words and phrases that must be "
        "preserved exactly as written. Use these spellings whenever the dictated "
        "audio matches them — even if the model would normally autocorrect or "
        "rephrase. Do not invent occurrences that aren't in the audio.\n"
        f"<preserve_exact>\n{joined}\n</preserve_exact>"
    )


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_dictation(request: CleanupRequest, user: CurrentUser):
    """Clean up raw dictated text via the OpenAI Responses API.

    Removes filler words, fixes grammar, adds proper punctuation, and formats
    the text while preserving the original meaning.
    """
    text = request.text.strip()
    if not text:
        return CleanupResponse(text="")

    if not user.dictation_post_filter_enabled:
        return CleanupResponse(text=text)

    if len(text) < 10:
        return CleanupResponse(text=text)

    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI cleanup is not configured (missing OPENAI_API_KEY).",
        )

    provider, model = validate_option(
        "dictation_post_filter",
        user.dictation_post_filter_provider,
        user.dictation_post_filter_model,
    )
    if provider != "openai":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unsupported dictation post-filter provider: {provider}",
        )

    vocabulary_block = _build_vocabulary_block(request.vocabulary)

    try:
        client = get_openai_client()
        response = await client.responses.create(
            model=model,
            instructions=DICTATION_CLEANUP_INSTRUCTIONS + vocabulary_block,
            input=(
                "<dictated_text>\n"
                f"{text}\n"
                "</dictated_text>"
            ),
            reasoning={"effort": "none"},
            text={"verbosity": "low"},
        )

        ensure_response_completed(response, operation="Dictation cleanup")
        cleaned = response_output_text(response)

        logger.info(
            "Dictation cleanup: %d chars → %d chars for user %s",
            len(text),
            len(cleaned),
            user.id,
        )
        return CleanupResponse(text=cleaned)

    except HTTPException:
        raise
    except openai.APIConnectionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to AI service",
        ) from None
    except openai.RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service rate limit exceeded. Please try again later.",
        ) from None
    except openai.APIStatusError as exc:
        logger.warning("Dictation cleanup upstream error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service error. Please try again later.",
        ) from exc
    except OpenAIResponseError as exc:
        logger.warning("Dictation cleanup incomplete response: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service returned an incomplete cleanup response.",
        ) from exc
    except Exception:
        logger.exception("Dictation cleanup failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dictation cleanup failed",
        ) from None


# ---------------------------------------------------------------------------
# Persistent dictation history + dictionary
# ---------------------------------------------------------------------------

MAX_DICTATION_RAW_TEXT_LENGTH = 100_000
MAX_DICTATION_CLEANED_TEXT_LENGTH = 100_000


class DictationEntryResponse(BaseModel):
    client_entry_id: UUID
    raw_text: str
    cleaned_text: str | None = None
    duration_seconds: float
    word_count: int
    occurred_at: datetime


class CreateDictationEntryRequest(BaseModel):
    client_entry_id: UUID
    raw_text: str = Field(max_length=MAX_DICTATION_RAW_TEXT_LENGTH)
    cleaned_text: str | None = Field(default=None, max_length=MAX_DICTATION_CLEANED_TEXT_LENGTH)
    duration_seconds: float = Field(ge=0)
    word_count: int = Field(ge=0)
    occurred_at: datetime


class DictionaryWordResponse(BaseModel):
    client_word_id: UUID
    word: str
    replacement: str | None = None
    occurred_at: datetime


class CreateDictionaryWordRequest(BaseModel):
    client_word_id: UUID
    word: str = Field(min_length=1, max_length=200)
    replacement: str | None = Field(default=None, max_length=200)
    occurred_at: datetime


def _serialize_entry(entry: DictationEntry) -> DictationEntryResponse:
    return DictationEntryResponse(
        client_entry_id=entry.client_entry_id,
        raw_text=entry.raw_text,
        cleaned_text=entry.cleaned_text,
        duration_seconds=entry.duration_seconds,
        word_count=entry.word_count,
        occurred_at=entry.occurred_at,
    )


def _serialize_word(word: DictationDictionaryWord) -> DictionaryWordResponse:
    return DictionaryWordResponse(
        client_word_id=word.client_word_id,
        word=word.word,
        replacement=word.replacement,
        occurred_at=word.occurred_at,
    )


@router.get("/entries", response_model=list[DictationEntryResponse])
async def list_dictation_entries(user: CurrentUser, db: Database) -> list[DictationEntryResponse]:
    """List the current user's dictation entries, newest first."""
    result = await db.execute(
        select(DictationEntry)
        .where(DictationEntry.user_id == user.id)
        .order_by(DictationEntry.occurred_at.desc())
    )
    return [_serialize_entry(entry) for entry in result.scalars().all()]


@router.post("/entries", response_model=DictationEntryResponse)
async def create_dictation_entry(
    request: CreateDictationEntryRequest,
    user: CurrentUser,
    db: Database,
    response: Response,
) -> DictationEntryResponse:
    """Create a dictation entry. Idempotent by (user_id, client_entry_id)."""
    existing = await db.execute(
        select(DictationEntry).where(
            DictationEntry.user_id == user.id,
            DictationEntry.client_entry_id == request.client_entry_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        response.status_code = status.HTTP_200_OK
        return _serialize_entry(found)

    entry = DictationEntry(
        user_id=user.id,
        client_entry_id=request.client_entry_id,
        raw_text=request.raw_text,
        cleaned_text=request.cleaned_text,
        duration_seconds=request.duration_seconds,
        word_count=request.word_count,
        occurred_at=request.occurred_at,
    )
    db.add(entry)
    await db.flush()
    logger.info(
        "Dictation entry stored: user=%s raw_len=%d cleaned_len=%s duration=%.2fs words=%d",
        user.id,
        len(request.raw_text),
        len(request.cleaned_text) if request.cleaned_text is not None else "null",
        request.duration_seconds,
        request.word_count,
    )
    response.status_code = status.HTTP_201_CREATED
    return _serialize_entry(entry)


@router.delete("/entries/{client_entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dictation_entry(
    client_entry_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Delete a dictation entry. Idempotent — returns 204 whether the row existed."""
    result = await db.execute(
        select(DictationEntry).where(
            DictationEntry.user_id == user.id,
            DictationEntry.client_entry_id == client_entry_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is not None:
        await db.delete(entry)
        await db.flush()


@router.get("/dictionary", response_model=list[DictionaryWordResponse])
async def list_dictionary_words(user: CurrentUser, db: Database) -> list[DictionaryWordResponse]:
    """List the current user's dictionary words, oldest first (matches client sort)."""
    result = await db.execute(
        select(DictationDictionaryWord)
        .where(DictationDictionaryWord.user_id == user.id)
        .order_by(DictationDictionaryWord.occurred_at.asc())
    )
    return [_serialize_word(word) for word in result.scalars().all()]


@router.post("/dictionary", response_model=DictionaryWordResponse)
async def create_dictionary_word(
    request: CreateDictionaryWordRequest,
    user: CurrentUser,
    db: Database,
    response: Response,
) -> DictionaryWordResponse:
    """Create a dictionary word. Idempotent by (user_id, client_word_id)."""
    existing = await db.execute(
        select(DictationDictionaryWord).where(
            DictationDictionaryWord.user_id == user.id,
            DictationDictionaryWord.client_word_id == request.client_word_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        response.status_code = status.HTTP_200_OK
        return _serialize_word(found)

    word = DictationDictionaryWord(
        user_id=user.id,
        client_word_id=request.client_word_id,
        word=request.word,
        replacement=request.replacement,
        occurred_at=request.occurred_at,
    )
    db.add(word)
    await db.flush()
    logger.info(
        "Dictation dictionary word stored: user=%s word_len=%d has_replacement=%s",
        user.id,
        len(request.word),
        request.replacement is not None,
    )
    response.status_code = status.HTTP_201_CREATED
    return _serialize_word(word)


@router.delete("/dictionary/{client_word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dictionary_word(
    client_word_id: UUID,
    user: CurrentUser,
    db: Database,
) -> None:
    """Delete a dictionary word. Idempotent — returns 204 whether the row existed."""
    result = await db.execute(
        select(DictationDictionaryWord).where(
            DictationDictionaryWord.user_id == user.id,
            DictationDictionaryWord.client_word_id == client_word_id,
        )
    )
    word = result.scalar_one_or_none()
    if word is not None:
        await db.delete(word)
        await db.flush()
