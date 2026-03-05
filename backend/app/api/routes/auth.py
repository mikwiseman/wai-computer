"""Authentication routes."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.security import (
    create_access_token,
    generate_magic_link_token,
    hash_password,
    verify_password,
)
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    """Request body for login."""

    email: EmailStr
    password: str


class MagicLinkRequest(BaseModel):
    """Request body for magic link."""

    email: EmailStr
    client: str | None = None


class VerifyMagicLinkRequest(BaseModel):
    """Request body for verifying magic link."""

    token: str


class TokenResponse(BaseModel):
    """Response with JWT token."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Response with user info."""

    id: str
    email: str
    created_at: datetime


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str


def _set_auth_cookie(response: Response, token: str) -> None:
    """Set HTTP-only auth cookie for browser sessions."""
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    """Clear the auth cookie."""
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


@router.post("/register", response_model=TokenResponse)
async def register(request: RegisterRequest, response: Response, db: Database) -> TokenResponse:
    """Register a new user."""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
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

    # Generate token
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)

    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, response: Response, db: Database) -> TokenResponse:
    """Login with email and password."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


@router.post("/magic-link", response_model=MessageResponse)
async def request_magic_link(request: MagicLinkRequest, db: Database) -> MessageResponse:
    """Send a magic link to the user's email."""
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

    # Send magic link email via Resend
    from app.core.email import send_magic_link_email

    await send_magic_link_email(user.email, token, client=request.client)

    return MessageResponse(message="Magic link sent to your email")


@router.post("/verify-magic", response_model=TokenResponse)
async def verify_magic_link(
    request: VerifyMagicLinkRequest,
    response: Response,
    db: Database,
) -> TokenResponse:
    """Verify a magic link token and return JWT."""
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

    # Generate JWT
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(response: Response, user: CurrentUser) -> TokenResponse:
    """Refresh the JWT token."""
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return TokenResponse(access_token=token)


@router.post("/logout", response_model=MessageResponse)
async def logout(response: Response) -> MessageResponse:
    """Clear auth cookie and log out browser session."""
    _clear_auth_cookie(response)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: CurrentUser) -> UserResponse:
    """Get current user info."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        created_at=user.created_at,
    )
