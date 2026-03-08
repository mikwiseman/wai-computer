"""Deepgram temporary token endpoint."""

import logging

import httpx
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deepgram"])

settings = get_settings()


@router.get("/deepgram-token")
async def get_deepgram_token(user: CurrentUser) -> dict:
    """Get a short-lived Deepgram JWT for direct client connection."""
    if not settings.deepgram_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcription service not configured",
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.deepgram.com/v1/auth/grant",
            headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            json={"ttl_seconds": 300},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
