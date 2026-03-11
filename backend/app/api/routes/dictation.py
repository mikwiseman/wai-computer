"""Dictation routes for AI text cleanup."""

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.config import get_settings

router = APIRouter(prefix="/dictation", tags=["dictation"])
logger = logging.getLogger(__name__)
MAX_CLEANUP_TEXT_LENGTH = 8_000


class CleanupRequest(BaseModel):
    """Request to clean up dictated text."""

    text: str = Field(max_length=MAX_CLEANUP_TEXT_LENGTH)


class CleanupResponse(BaseModel):
    """Response with cleaned text."""

    text: str


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

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        message = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Clean up this dictated text. "
                        "Remove filler words "
                        "(um, uh, like, you know, I mean, basically, actually, so, well). "
                        "Fix grammar and punctuation. "
                        "Remove false starts and self-corrections "
                        "(keep only the final intended version). "
                        "Preserve the original meaning, tone, and style. "
                        "Do NOT add information, change the meaning, or make it more formal "
                        "unless the text is clearly informal. "
                        "Output ONLY the cleaned text, nothing else.\n\n"
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
