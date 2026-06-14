"""Security utilities for password hashing and JWT tokens."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def _bcrypt_password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(_bcrypt_password_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    try:
        return bcrypt.checkpw(
            _bcrypt_password_bytes(plain_password),
            hashed_password.encode("ascii"),
        )
    except ValueError:
        return False


def create_access_token(user_id: UUID, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)

    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID | None:
    """Decode and validate a JWT access token. Returns user_id or None if invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            return None
        return UUID(user_id_str)
    except (JWTError, ValueError):
        return None


def generate_magic_link_token() -> str:
    """Generate a secure token for magic link authentication."""
    return secrets.token_urlsafe(32)


def generate_refresh_token() -> str:
    """Generate a cryptographically secure refresh token."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token using SHA-256 for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


EMAIL_VERIFY_PURPOSE = "email_verify"


def create_email_verification_token(
    user_id: UUID, email: str, *, expires_minutes: int = 1440
) -> str:
    """Signed, self-contained token proving a user controls ``email`` (24h default).

    Carries the target user + pending email so confirming the email never trusts an
    unverified provider claim (NoAuth-safe) and needs no extra column.
    """
    now = datetime.now(timezone.utc)
    to_encode = {
        "sub": str(user_id),
        "email": email,
        "purpose": EMAIL_VERIFY_PURPOSE,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_email_verification_token(token: str) -> tuple[UUID, str] | None:
    """Return (user_id, email) for a valid email-verify token, else None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("purpose") != EMAIL_VERIFY_PURPOSE:
        return None
    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        return None
    try:
        return UUID(str(sub)), str(email)
    except ValueError:
        return None
