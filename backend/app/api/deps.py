"""API dependencies for authentication and database access."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.observability import bind_user_context
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

settings = get_settings()
bearer_security = HTTPBearer(auto_error=False)


def _extract_access_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Extract access token from Authorization header or auth cookie."""
    if credentials is not None:
        return credentials.credentials

    cookie_token = request.cookies.get(settings.auth_cookie_name)
    if cookie_token:
        return cookie_token

    return None


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Dependency to get the current authenticated user.

    Raises:
        HTTPException: If token is invalid or user not found
    """
    token = _extract_access_token(request, credentials)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    bind_user_context(str(user.id))
    return user


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """
    Dependency to optionally get the current authenticated user.

    Returns None if no token provided or token is invalid.
    """
    token = _extract_access_token(request, credentials)
    if token is None:
        return None

    user_id = decode_access_token(token)

    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        bind_user_context(str(user.id))
    return user


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
Database = Annotated[AsyncSession, Depends(get_db)]


def payment_mode_override(request: Request) -> bool:
    """Per-request opt-in to billing enforcement.

    Mac/web clients send ``X-WaiComputer-Payment-Mode: enforce`` when the
    user has flipped the Payment mode toggle in Settings — this lets a
    tester run the real quota/402/Upgrade flow against themselves without
    flipping the global env switch and breaking everyone else.
    """
    value = request.headers.get("x-waicomputer-payment-mode")
    return value is not None and value.lower() == "enforce"


PaymentModeOverride = Annotated[bool, Depends(payment_mode_override)]
