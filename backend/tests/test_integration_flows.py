"""Integration-style tests exercising complex multi-step flows across the API.

Each test walks through an end-to-end scenario, calling multiple endpoints
in sequence and verifying that state mutations propagate correctly.
"""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.models.user import User
from tests.conftest import LEGAL_ACCEPTANCE

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
        json={"email": email, "password": "password123", **LEGAL_ACCEPTANCE},
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
