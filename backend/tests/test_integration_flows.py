"""Integration-style tests exercising complex multi-step flows across the API.

Each test walks through an end-to-end scenario, calling multiple endpoints
in sequence and verifying that state mutations propagate correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import get_rate_limiter
from app.core.security import decode_access_token
from app.core.summarizer import SummaryResult
from app.models.recording import ActionItem
from app.models.user import User

# --- helpers ---


def _unique_email(prefix: str = "flow") -> str:
    """Generate a unique email to avoid collisions with leftover DB state."""
    return f"{prefix}-{uuid4().hex[:8]}@example.com"


async def _register(
    client: AsyncClient, email: str | None = None
) -> tuple[dict[str, str], str, str]:
    """Register a user and return (headers, token, email)."""
    if email is None:
        email = _unique_email()
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token, email


async def _user_from_token(db: AsyncSession, token: str) -> User:
    uid = decode_access_token(token)
    assert uid is not None
    user = await db.get(User, uid)
    assert user is not None
    return user


async def _create_recording(
    client: AsyncClient,
    headers: dict,
    title: str | None = "Test Recording",
    type_: str = "note",
) -> dict:
    resp = await client.post(
        "/api/recordings",
        headers=headers,
        json={"title": title, "type": type_, "language": "en"},
    )
    assert resp.status_code == 201
    return resp.json()

