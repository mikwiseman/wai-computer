"""Authentication routes."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sentry_sdk
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.observability import bind_user_context
from app.core.rate_limit import (
    check_login_rate_limit,
    check_magic_link_rate_limit,
    check_register_rate_limit,
)
from app.core.security import (
    create_access_token,
    generate_magic_link_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken as RefreshTokenModel
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Password cannot be only whitespace")
        if len(v.strip()) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    """Request body for login."""

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()


class MagicLinkRequest(BaseModel):
    """Request body for magic link."""

    email: EmailStr
    client: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()


class VerifyMagicLinkRequest(BaseModel):
    """Request body for verifying magic link."""

    token: str


class TokenResponse(BaseModel):
    """Response with JWT token."""

    access_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    """Response with access + refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Request to refresh tokens."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Request to logout (optional refresh token for server-side cleanup)."""

    refresh_token: str | None = None


class UserResponse(BaseModel):
    """Response with user info."""

    id: str
    email: str
    created_at: datetime


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str


def _set_access_cookie(response: Response, token: str) -> None:
    """Set the short-lived HTTP-only access cookie for browser sessions."""
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure_resolved,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.jwt_access_expire_minutes * 60,
        path="/",
        domain=settings.auth_cookie_domain_resolved,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the long-lived HTTP-only refresh cookie for browser sessions."""
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure_resolved,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.jwt_refresh_expire_days * 24 * 60 * 60,
        path="/",
        domain=settings.auth_cookie_domain_resolved,
    )


def _clear_auth_cookies(response: Response) -> None:
    """Clear browser auth cookies."""
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure_resolved,
        samesite=settings.auth_cookie_samesite,
        path="/",
        domain=settings.auth_cookie_domain_resolved,
    )
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure_resolved,
        samesite=settings.auth_cookie_samesite,
        path="/",
        domain=settings.auth_cookie_domain_resolved,
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set both access and refresh cookies for browser sessions."""
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)


def _extract_refresh_token(
    request_body: RefreshRequest | LogoutRequest | None,
    raw_request: Request,
) -> str | None:
    """Resolve refresh token from JSON body first, then HTTP-only refresh cookie."""
    body_refresh_token = getattr(request_body, "refresh_token", None)
    if body_refresh_token:
        return body_refresh_token
    return raw_request.cookies.get(settings.auth_refresh_cookie_name)


async def _create_auth_tokens(
    user_id: UUID, db: AsyncSession, device_name: str | None = None
) -> tuple[str, str]:
    """Create access + refresh token pair. Stores refresh token hash in DB."""
    access_token = create_access_token(
        user_id, expires_delta=timedelta(minutes=settings.jwt_access_expire_minutes)
    )
    refresh_token_value = generate_refresh_token()
    refresh_token_hash = hash_refresh_token(refresh_token_value)

    db_token = RefreshTokenModel(
        user_id=user_id,
        token_hash=refresh_token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days),
        device_name=device_name,
    )
    db.add(db_token)
    await db.flush()

    return access_token, refresh_token_value


@router.post(
    "/register",
    response_model=AuthResponse,
    dependencies=[Depends(check_register_rate_limit)],
)
async def register(request: RegisterRequest, response: Response, db: Database) -> AuthResponse:
    """Register a new user."""
    sentry_sdk.add_breadcrumb(category="auth", message="User registration attempt", level="info")
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        logger.info("registration rejected duplicate_email=%s", request.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
    )
    db.add(user)
    await db.flush()

    # Generate tokens
    access_token, refresh_token = await _create_auth_tokens(user.id, db)
    bind_user_context(str(user.id))
    _set_auth_cookies(response, access_token, refresh_token)
    logger.info("registration succeeded email=%s", user.email)

    return AuthResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(check_login_rate_limit)])
async def login(request: LoginRequest, response: Response, db: Database) -> AuthResponse:
    """Login with email and password."""
    sentry_sdk.add_breadcrumb(category="auth", message="User login attempt", level="info")
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        logger.info("login rejected email=%s reason=user_not_found", request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(request.password, user.password_hash):
        logger.info("login rejected email=%s reason=bad_password", request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token, refresh_token = await _create_auth_tokens(user.id, db)
    bind_user_context(str(user.id))
    _set_auth_cookies(response, access_token, refresh_token)
    logger.info("login succeeded email=%s", user.email)
    return AuthResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/magic-link",
    response_model=MessageResponse,
    dependencies=[Depends(check_magic_link_rate_limit)],
)
async def request_magic_link(request: MagicLinkRequest, db: Database) -> MessageResponse:
    """Send a magic link to the user's email."""
    sentry_sdk.add_breadcrumb(category="auth", message="Magic link requested", level="info")
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None:
        # Create user without password for magic link auth
        user = User(email=request.email)
        db.add(user)
        await db.flush()

    # Generate magic link token
    token = generate_magic_link_token()
    user.magic_link_token = token
    user.magic_link_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    await db.flush()

    # Send magic link email via Resend
    from app.core.email import send_magic_link_email

    await send_magic_link_email(user.email, token, client=request.client)

    return MessageResponse(message="Magic link sent to your email")


@router.post("/verify-magic", response_model=AuthResponse)
async def verify_magic_link(
    request: VerifyMagicLinkRequest,
    response: Response,
    db: Database,
) -> AuthResponse:
    """Verify a magic link token and return JWT."""
    sentry_sdk.add_breadcrumb(category="auth", message="Magic link verification", level="info")
    result = await db.execute(
        select(User).where(User.magic_link_token == request.token)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid magic link",
        )

    if user.magic_link_expires is None or user.magic_link_expires < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Magic link expired",
        )

    # Clear magic link
    user.magic_link_token = None
    user.magic_link_expires = None

    # Generate tokens
    access_token, refresh_token = await _create_auth_tokens(user.id, db)
    bind_user_context(str(user.id))
    _set_auth_cookies(response, access_token, refresh_token)
    logger.info("magic_link verification succeeded email=%s", user.email)
    return AuthResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(
    raw_request: Request,
    response: Response,
    db: Database,
    request: RefreshRequest | None = Body(default=None),
) -> AuthResponse:
    """Refresh tokens using a valid refresh token. Does NOT require a valid access token."""
    sentry_sdk.add_breadcrumb(category="auth", message="Token refresh attempt", level="info")
    refresh_source = "body" if request and request.refresh_token else "cookie"
    refresh_token_value = _extract_refresh_token(request, raw_request)
    if not refresh_token_value:
        logger.info("refresh rejected source=%s reason=missing_token", refresh_source)
        raise HTTPException(status_code=401, detail="Refresh token required")

    token_hash = hash_refresh_token(refresh_token_value)
    result = await db.execute(
        select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()

    if db_token is None:
        logger.info("refresh rejected source=%s reason=invalid_token", refresh_source)
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if db_token.expires_at < datetime.now(timezone.utc):
        await db.delete(db_token)
        await db.flush()
        logger.info("refresh rejected source=%s reason=expired_token", refresh_source)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    # Token rotation: delete old, create new pair
    user_id = db_token.user_id
    await db.delete(db_token)
    await db.flush()

    access_token, new_refresh_token = await _create_auth_tokens(user_id, db)
    bind_user_context(str(user_id))
    _set_auth_cookies(response, access_token, new_refresh_token)
    logger.info("refresh succeeded source=%s", refresh_source)
    return AuthResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    raw_request: Request,
    response: Response,
    db: Database,
    request: LogoutRequest | None = Body(default=None),
) -> MessageResponse:
    """Clear auth cookie and revoke refresh token."""
    sentry_sdk.add_breadcrumb(category="auth", message="User logout", level="info")
    _clear_auth_cookies(response)
    refresh_token_value = _extract_refresh_token(request, raw_request)
    if refresh_token_value:
        token_hash = hash_refresh_token(refresh_token_value)
        result = await db.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        db_token = result.scalar_one_or_none()
        if db_token:
            bind_user_context(str(db_token.user_id))
            await db.delete(db_token)
            await db.flush()
            logger.info("logout succeeded token_revoked=true")
        else:
            logger.info("logout completed token_revoked=false")
    else:
        logger.info("logout completed token_revoked=false source=none")
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: CurrentUser) -> UserResponse:
    """Get current user info."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        created_at=user.created_at,
    )
