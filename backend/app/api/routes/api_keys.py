"""Personal Access Token (API key) management routes.

Session-only (a token cannot mint, list, or revoke tokens). The plaintext key is
returned exactly once, at creation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Database, SessionUser
from app.core.api_keys import API_KEY_READ_SCOPE, generate_api_key
from app.models.api_key import ApiKey

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    prefix: str
    last4: str
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    token: str  # plaintext, shown exactly once


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(user: SessionUser, db: Database) -> list[ApiKey]:
    """List the current user's active API keys (never the token itself)."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: CreateApiKeyRequest, user: SessionUser, db: Database
) -> ApiKeyCreatedResponse:
    """Create a read-only API key; return the plaintext token once."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name is required"
        )
    plaintext, token_hash_value, prefix, last4 = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,
        name=name,
        token_hash=token_hash_value,
        prefix=prefix,
        last4=last4,
        scopes=[API_KEY_READ_SCOPE],
        expires_at=payload.expires_at,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    return ApiKeyCreatedResponse(
        **ApiKeyResponse.model_validate(api_key).model_dump(),
        token=plaintext,
    )


@router.post("/{key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: UUID, user: SessionUser, db: Database) -> Response:
    """Revoke one of the current user's API keys."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == user.id,
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    api_key.revoked_at = datetime.now(timezone.utc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
