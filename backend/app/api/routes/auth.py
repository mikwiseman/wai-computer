"""Authentication routes."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.core.observability import (
    add_sentry_breadcrumb,
    bind_user_context,
    safe_email_metadata,
    safe_text_digest,
)
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
from app.models.person import Voiceprint
from app.models.refresh_token import RefreshToken as RefreshTokenModel
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)
VALID_REGIONS = {"global", "ru"}
MAGIC_LINK_TOKEN_PREFIX = "magic_"
PASSWORD_RESET_TOKEN_PREFIX = "reset_"
LEGAL_TERMS_VERSION = "2026-05-22"
LEGAL_PRIVACY_VERSION = "2026-05-22"
AUTH_MESSAGES = {
    "en": {
        "register_unavailable": (
            "Unable to create account. Try signing in or request a magic link."
        ),
        "invalid_credentials": "Invalid email or password",
        "magic_link_sent": "Magic link sent to your email",
        "invalid_magic_link": "Invalid magic link",
        "magic_link_expired": "Magic link expired",
        "forgot_password_sent": (
            "If this email is registered, we sent a password reset link."
        ),
        "password_reset_delivery_failed": "Could not send email. Try again later.",
        "invalid_password_reset": "Invalid password reset link",
        "password_reset_expired": "Password reset link expired",
        "password_reset_success": "Password reset successfully",
        "legal_acceptance_required": "Legal acceptance required",
        "legal_acceptance_current_required": "Current legal documents must be accepted",
    },
    "ru": {
        "register_unavailable": (
            "Не получилось создать аккаунт. Попробуй войти или запросить ссылку для входа."
        ),
        "invalid_credentials": "Неверный email или пароль",
        "magic_link_sent": "Мы отправили ссылку для входа на твою почту.",
        "invalid_magic_link": "Недействительная ссылка для входа",
        "magic_link_expired": "Срок действия ссылки для входа истек",
        "forgot_password_sent": (
            "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля."
        ),
        "password_reset_delivery_failed": "Не удалось отправить письмо. Попробуйте позже.",
        "invalid_password_reset": "Недействительная ссылка для сброса пароля",
        "password_reset_expired": "Срок действия ссылки для сброса пароля истек",
        "password_reset_success": "Пароль успешно сброшен",
        "legal_acceptance_required": "Нужно принять юридические документы",
        "legal_acceptance_current_required": "Нужно принять актуальные юридические документы",
    },
}


def _normalize_region(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in VALID_REGIONS:
        raise ValueError(f"region must be one of: {', '.join(sorted(VALID_REGIONS))}")
    return normalized


def _normalize_locale(value: str | None, region: str | None = None) -> str:
    if value and value.strip().lower().startswith("ru"):
        return "ru"
    if region == "ru":
        return "ru"
    return "en"


def _password_min_length(value: str) -> str:
    if not value.strip():
        raise ValueError("Password cannot be only whitespace")
    if len(value.strip()) < 8:
        raise ValueError("Password must be at least 8 characters")
    return value


def _new_magic_token() -> str:
    return f"{MAGIC_LINK_TOKEN_PREFIX}{generate_magic_link_token()}"


def _new_password_reset_token() -> str:
    return f"{PASSWORD_RESET_TOKEN_PREFIX}{generate_magic_link_token()}"


def _is_password_reset_token(token: str) -> bool:
    return token.startswith(PASSWORD_RESET_TOKEN_PREFIX)


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str
    region: str = "global"
    locale: str | None = None
    accepted_legal_terms: bool = False
    legal_terms_version: str | None = None
    legal_privacy_version: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        return _password_min_length(v)

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        return _normalize_region(v)


class LoginRequest(BaseModel):
    """Request body for login."""

    email: EmailStr
    password: str
    locale: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()


class MagicLinkRequest(BaseModel):
    """Request body for magic link."""

    email: EmailStr
    client: str | None = None
    region: str = "global"
    locale: str | None = None
    accepted_legal_terms: bool = False
    legal_terms_version: str | None = None
    legal_privacy_version: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        return _normalize_region(v)


class VerifyMagicLinkRequest(BaseModel):
    """Request body for verifying magic link."""

    token: str
    locale: str | None = None


class ForgotPasswordRequest(BaseModel):
    """Request body for password reset email."""

    email: EmailStr
    locale: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()


class ResetPasswordRequest(BaseModel):
    """Request body for setting a new password from a reset token."""

    token: str
    password: str
    locale: str | None = None

    @field_validator("token")
    @classmethod
    def token_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Token is required")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        return _password_min_length(v)


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
    has_password: bool
    region: str
    # True once the account has at least one enrolled voiceprint. Clients use
    # this as the cross-device source of truth for "already onboarded" so a
    # returning user is not shown voice onboarding again on a fresh device.
    has_enrolled_voice: bool


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


def _require_current_legal_acceptance(
    *,
    accepted: bool,
    terms_version: str | None,
    privacy_version: str | None,
    locale: str,
) -> None:
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AUTH_MESSAGES[locale]["legal_acceptance_required"],
        )
    if terms_version != LEGAL_TERMS_VERSION or privacy_version != LEGAL_PRIVACY_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AUTH_MESSAGES[locale]["legal_acceptance_current_required"],
        )


def _record_legal_acceptance(user: User, *, locale: str, source: str) -> None:
    user.legal_terms_accepted_at = datetime.now(timezone.utc)
    user.legal_terms_version = LEGAL_TERMS_VERSION
    user.legal_privacy_version = LEGAL_PRIVACY_VERSION
    user.legal_acceptance_locale = locale
    user.legal_acceptance_source = source


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
    response_model=AuthResponse | MessageResponse,
    dependencies=[Depends(check_register_rate_limit)],
)
async def register(
    request: RegisterRequest, response: Response, db: Database
) -> AuthResponse | MessageResponse:
    """Register a new user."""
    add_sentry_breadcrumb(category="auth", message="User registration attempt")
    locale = _normalize_locale(request.locale, request.region)
    password_hash = hash_password(request.password)

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        if existing_user.password_hash is None:
            _require_current_legal_acceptance(
                accepted=request.accepted_legal_terms,
                terms_version=request.legal_terms_version,
                privacy_version=request.legal_privacy_version,
                locale=locale,
            )
            existing_user.password_hash = password_hash
            existing_user.magic_link_token = None
            existing_user.magic_link_expires = None
            _record_legal_acceptance(existing_user, locale=locale, source="password")
            await db.flush()

            access_token, refresh_token = await _create_auth_tokens(existing_user.id, db)
            bind_user_context(str(existing_user.id))
            _set_auth_cookies(response, access_token, refresh_token)
            logger.info(
                "registration completed passwordless_account email=%s",
                safe_text_digest(request.email, label="email"),
            )
            return AuthResponse(access_token=access_token, refresh_token=refresh_token)

        logger.info(
            "registration rejected reason=duplicate_email email=%s",
            safe_text_digest(request.email, label="email"),
        )
        return MessageResponse(message=AUTH_MESSAGES[locale]["register_unavailable"])

    _require_current_legal_acceptance(
        accepted=request.accepted_legal_terms,
        terms_version=request.legal_terms_version,
        privacy_version=request.legal_privacy_version,
        locale=locale,
    )

    # Create user
    user = User(
        email=request.email,
        password_hash=password_hash,
        region=request.region,
    )
    _record_legal_acceptance(user, locale=locale, source="password")
    db.add(user)
    await db.flush()

    # Generate tokens
    access_token, refresh_token = await _create_auth_tokens(user.id, db)
    bind_user_context(str(user.id))
    _set_auth_cookies(response, access_token, refresh_token)
    logger.info("registration succeeded")

    return AuthResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(check_login_rate_limit)])
async def login(request: LoginRequest, response: Response, db: Database) -> AuthResponse:
    """Login with email and password."""
    locale = _normalize_locale(request.locale)
    add_sentry_breadcrumb(
        category="auth",
        message="User login attempt",
        data=safe_email_metadata(request.email),
    )
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        logger.info(
            "login rejected reason=user_not_found email=%s",
            safe_text_digest(request.email, label="email"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["invalid_credentials"],
        )

    if not verify_password(request.password, user.password_hash):
        logger.info(
            "login rejected reason=bad_password email=%s",
            safe_text_digest(request.email, label="email"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["invalid_credentials"],
        )

    access_token, refresh_token = await _create_auth_tokens(user.id, db)
    bind_user_context(str(user.id))
    _set_auth_cookies(response, access_token, refresh_token)
    logger.info("login succeeded")
    return AuthResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/magic-link",
    response_model=MessageResponse,
    dependencies=[Depends(check_magic_link_rate_limit)],
)
async def request_magic_link(request: MagicLinkRequest, db: Database) -> MessageResponse:
    """Send a magic link to the user's email."""
    add_sentry_breadcrumb(
        category="auth",
        message="Magic link requested",
        data=safe_email_metadata(request.email),
    )
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    locale = _normalize_locale(request.locale, request.region)

    if user is None:
        _require_current_legal_acceptance(
            accepted=request.accepted_legal_terms,
            terms_version=request.legal_terms_version,
            privacy_version=request.legal_privacy_version,
            locale=locale,
        )
        # Create user without password for magic link auth
        user = User(email=request.email, region=request.region)
        _record_legal_acceptance(user, locale=locale, source="magic_link")
        db.add(user)
        await db.flush()

    # Generate magic link token
    token = _new_magic_token()
    user.magic_link_token = token
    user.magic_link_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    await db.flush()

    # Send magic link email via Resend
    from app.core.email import send_magic_link_email

    await send_magic_link_email(
        user.email,
        token,
        client=request.client,
        locale=locale,
    )
    logger.info(
        "magic_link requested client=%s email=%s user_created=%s",
        request.client or "-",
        safe_text_digest(request.email, label="email"),
        user.password_hash is None,
    )

    return MessageResponse(message=AUTH_MESSAGES[locale]["magic_link_sent"])


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    dependencies=[Depends(check_magic_link_rate_limit)],
)
async def forgot_password(request: ForgotPasswordRequest, db: Database) -> MessageResponse:
    """Send a password reset link when the email belongs to an account."""
    locale = _normalize_locale(request.locale)
    add_sentry_breadcrumb(
        category="auth",
        message="Password reset requested",
        data=safe_email_metadata(request.email),
    )
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is not None:
        from app.core.email import send_password_reset_email

        token = _new_password_reset_token()
        user.magic_link_token = token
        user.magic_link_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        await db.flush()
        try:
            await send_password_reset_email(user.email, token, locale=locale)
        except Exception:
            logger.exception(
                "password_reset email delivery failed email=%s",
                safe_text_digest(request.email, label="email"),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=AUTH_MESSAGES[locale]["password_reset_delivery_failed"],
            ) from None
        logger.info(
            "password_reset requested email=%s",
            safe_text_digest(request.email, label="email"),
        )
    else:
        logger.info(
            "password_reset requested missing_email=%s",
            safe_text_digest(request.email, label="email"),
        )

    return MessageResponse(message=AUTH_MESSAGES[locale]["forgot_password_sent"])


@router.post("/verify-magic", response_model=AuthResponse)
async def verify_magic_link(
    request: VerifyMagicLinkRequest,
    response: Response,
    db: Database,
) -> AuthResponse:
    """Verify a magic link token and return JWT."""
    locale = _normalize_locale(request.locale)
    add_sentry_breadcrumb(category="auth", message="Magic link verification")
    if _is_password_reset_token(request.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["invalid_magic_link"],
        )

    result = await db.execute(
        select(User).where(User.magic_link_token == request.token)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["invalid_magic_link"],
        )

    if user.magic_link_expires is None or user.magic_link_expires < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["magic_link_expired"],
        )

    # Clear magic link
    user.magic_link_token = None
    user.magic_link_expires = None

    # Generate tokens
    access_token, refresh_token = await _create_auth_tokens(user.id, db)
    bind_user_context(str(user.id))
    _set_auth_cookies(response, access_token, refresh_token)
    logger.info("magic_link verification succeeded")
    return AuthResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest,
    db: Database,
) -> MessageResponse:
    """Set a new password from a password reset token."""
    locale = _normalize_locale(request.locale)
    add_sentry_breadcrumb(category="auth", message="Password reset verification")

    if not _is_password_reset_token(request.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["invalid_password_reset"],
        )

    result = await db.execute(select(User).where(User.magic_link_token == request.token))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["invalid_password_reset"],
        )

    if user.magic_link_expires is None or user.magic_link_expires < datetime.now(timezone.utc):
        user.magic_link_token = None
        user.magic_link_expires = None
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AUTH_MESSAGES[locale]["password_reset_expired"],
        )

    user.password_hash = hash_password(request.password)
    user.magic_link_token = None
    user.magic_link_expires = None
    await db.flush()

    bind_user_context(str(user.id))
    logger.info("password_reset completed")
    return MessageResponse(message=AUTH_MESSAGES[locale]["password_reset_success"])


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(
    raw_request: Request,
    response: Response,
    db: Database,
    request: RefreshRequest | None = Body(default=None),
) -> AuthResponse:
    """Refresh tokens using a valid refresh token. Does NOT require a valid access token."""
    add_sentry_breadcrumb(category="auth", message="Token refresh attempt")
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
    add_sentry_breadcrumb(category="auth", message="User logout")
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
async def get_current_user_info(user: CurrentUser, db: Database) -> UserResponse:
    """Get current user info."""
    enrolled = await db.execute(
        select(Voiceprint.id).where(Voiceprint.user_id == user.id).limit(1)
    )
    return UserResponse(
        id=str(user.id),
        email=user.email,
        created_at=user.created_at,
        has_password=user.password_hash is not None,
        region=user.region,
        has_enrolled_voice=enrolled.first() is not None,
    )


@router.delete("/me", response_model=MessageResponse)
async def delete_current_account(
    response: Response,
    user: CurrentUser,
    db: Database,
) -> MessageResponse:
    """Permanently delete the current user and all their data.

    Cascades through SQLAlchemy relationships + ON DELETE CASCADE on the
    refresh_tokens FK, so recordings, folders, entities, tags, summaries,
    highlights, and active sessions are all removed. Auth cookies are cleared
    so the browser session also terminates.

    This endpoint exists to satisfy App Store review guideline 5.1.1(v):
    apps that support account creation must offer in-app account deletion.
    """
    bind_user_context(str(user.id))
    add_sentry_breadcrumb(category="auth", message="account_delete_requested")
    user_id = user.id

    await db.delete(user)
    await db.commit()

    _clear_auth_cookies(response)
    logger.info("account_deleted user_id=%s", user_id)
    return MessageResponse(message="Account deleted")
