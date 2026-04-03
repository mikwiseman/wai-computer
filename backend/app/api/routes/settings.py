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
        if len(v.strip()) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str


VALID_SUMMARY_STYLES = {"brief", "medium", "detailed"}


class SettingsResponse(BaseModel):
    """Response for user settings."""

    default_language: str
    summary_language: str
    summary_style: str
    summary_instructions: str | None


class UpdateSettingsRequest(BaseModel):
    """Request to update user settings."""

    default_language: str | None = None
    summary_language: str | None = None
    summary_style: str | None = None
    summary_instructions: str | None = None

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("default_language cannot be empty")
        return normalized

    @field_validator("summary_language")
    @classmethod
    def normalize_summary_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("summary_language cannot be empty")
        return normalized

    @field_validator("summary_style")
    @classmethod
    def validate_summary_style(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in VALID_SUMMARY_STYLES:
            valid = ", ".join(sorted(VALID_SUMMARY_STYLES))
            raise ValueError(f"summary_style must be one of: {valid}")
        return normalized


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: CurrentUser,
) -> SettingsResponse:
    """Get user settings."""
    return SettingsResponse(
        default_language=user.default_language,
        summary_language=user.summary_language,
        summary_style=user.summary_style,
        summary_instructions=user.summary_instructions,
    )


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    request: UpdateSettingsRequest,
    user: CurrentUser,
    db: Database,
) -> SettingsResponse:
    """Update user settings."""
    if request.default_language is not None:
        user.default_language = request.default_language
    if request.summary_language is not None:
        user.summary_language = request.summary_language
    if request.summary_style is not None:
        user.summary_style = request.summary_style
    # summary_instructions: allow explicit empty string to clear
    if request.summary_instructions is not None:
        user.summary_instructions = request.summary_instructions or None
    await db.flush()
    return SettingsResponse(
        default_language=user.default_language,
        summary_language=user.summary_language,
        summary_style=user.summary_style,
        summary_instructions=user.summary_instructions,
    )


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
