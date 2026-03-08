"""Deepgram token endpoint."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.config import get_settings

router = APIRouter(tags=["deepgram"])

settings = get_settings()


@router.get("/deepgram-token")
async def get_deepgram_token(user: CurrentUser) -> dict:
    """Return a Deepgram token for direct client WebSocket connection."""
    if not settings.deepgram_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription service not configured",
        )

    return {"access_token": settings.deepgram_api_key}
