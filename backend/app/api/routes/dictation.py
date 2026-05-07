"""Dictation routes for AI text cleanup."""

import logging

import anthropic
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.config import get_settings
from app.core.qa import _get_anthropic_client

router = APIRouter(prefix="/dictation", tags=["dictation"])
logger = logging.getLogger(__name__)
MAX_CLEANUP_TEXT_LENGTH = 8_000
MAX_CLEANUP_VOCABULARY_ENTRIES = 200
MAX_CLEANUP_VOCABULARY_ENTRY_CHARS = 60


class CleanupRequest(BaseModel):
    """Request to clean up dictated text."""

    text: str = Field(max_length=MAX_CLEANUP_TEXT_LENGTH)
    vocabulary: list[str] | None = Field(default=None)


class CleanupResponse(BaseModel):
    """Response with cleaned text."""

    text: str


def _build_vocabulary_block(vocabulary: list[str] | None) -> str:
    """Render the user's dictionary as an Anthropic-style preserve block.

    Per Anthropic prompt-engineering guidance, vocabulary that must survive
    the cleanup pass goes inside an explicit XML tag rather than inline
    prose — Claude treats tagged content as structured, not as suggestion.
    Caps avoid pathological lists drowning out the cleanup instructions.
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
        "audio matches them — even if Claude would normally autocorrect or "
        "rephrase. Do not invent occurrences that aren't in the audio.\n"
        f"<preserve_exact>\n{joined}\n</preserve_exact>"
    )


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_dictation(request: CleanupRequest, user: CurrentUser):
    """Clean up raw dictated text using Claude AI.

    Removes filler words, fixes grammar, adds proper punctuation,
    and formats the text while preserving the original meaning.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI cleanup is not configured (missing ANTHROPIC_API_KEY).",
        )

    text = request.text.strip()
    if not text:
        return CleanupResponse(text="")

    # Short texts (< 10 chars) don't need AI cleanup
    if len(text) < 10:
        return CleanupResponse(text=text)

    vocabulary_block = _build_vocabulary_block(request.vocabulary)

    try:
        client = _get_anthropic_client()

        message = await client.messages.create(
            model=settings.anthropic_dictation_model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Lightly clean up this dictated text. "
                        "Remove filler sounds and filler words in Russian and English, including "
                        "э, эээ, э-э-э, а, ааа, а-а-а, ну, вот, типа, как бы, значит, "
                        "um, uh, like, you know, I mean, basically, actually, so, well. "
                        "Remove repeated filler-only loops such as 'и, э-э-э, и, э-э-э'. "
                        "Remove false starts and self-corrections, keeping only the final intended "
                        "version, for example 'мы х-- мы предлагаем' becomes 'мы предлагаем'. "
                        "Fix only obvious grammar, capitalization, and punctuation issues. "
                        "Preserve the original language, meaning, tone, style, terminology, names, "
                        "claims, and sentence order. "
                        "Do not summarize, add information, change the meaning, or make it more "
                        "formal unless the text is clearly formal already. "
                        "Output ONLY the cleaned text, nothing else."
                        f"{vocabulary_block}\n\n"
                        f"Dictated text: {text}"
                    ),
                }
            ],
        )

        if not message.content:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Empty response from AI service",
            )

        first_block = message.content[0]
        cleaned = getattr(first_block, "text", "").strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Empty response from AI service",
            )

        logger.info(
            "Dictation cleanup: %d chars → %d chars for user %s",
            len(text),
            len(cleaned),
            user.id,
        )
        return CleanupResponse(text=cleaned)

    except HTTPException:
        raise
    except anthropic.APIConnectionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to connect to AI service",
        ) from None
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service rate limit exceeded. Please try again later.",
        ) from None
    except anthropic.APIStatusError as exc:
        logger.warning("Dictation cleanup upstream error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service error. Please try again later.",
        ) from exc
    except Exception:
        logger.exception("Dictation cleanup failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dictation cleanup failed",
        ) from None
