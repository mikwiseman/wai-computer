"""User settings routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from app.api.deps import CurrentUser, Database
from app.core.security import hash_password, verify_password

router = APIRouter(prefix="/settings", tags=["settings"])


class ChangePasswordRequest(BaseModel):
    """Request to change password."""

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str


class SettingsResponse(BaseModel):
    """Response for user settings."""

    default_language: str


class UpdateSettingsRequest(BaseModel):
    """Request to update user settings."""

    default_language: str | None = None

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("default_language cannot be empty")
        return normalized


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: CurrentUser,
) -> SettingsResponse:
    """Get user settings."""
    return SettingsResponse(default_language=user.default_language)


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    request: UpdateSettingsRequest,
    user: CurrentUser,
    db: Database,
) -> SettingsResponse:
    """Update user settings."""
    if request.default_language is not None:
        user.default_language = request.default_language
    await db.flush()
    return SettingsResponse(default_language=user.default_language)


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    user: CurrentUser,
    db: Database,
) -> MessageResponse:
    """Change user password."""
    if user.password_hash is None:
        # User registered via magic link, allow setting password
        user.password_hash = hash_password(request.new_password)
        await db.flush()
        return MessageResponse(message="Password set successfully")

    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    user.password_hash = hash_password(request.new_password)
    await db.flush()

    return MessageResponse(message="Password changed successfully")
