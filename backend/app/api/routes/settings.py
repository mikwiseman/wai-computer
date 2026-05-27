"""User settings routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator

from app.api.deps import CurrentUser, Database
from app.config import get_settings as get_app_settings
from app.core.security import hash_password, verify_password
from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_DICTATION_POST_FILTER_MODEL,
    DEFAULT_DICTATION_POST_FILTER_PROVIDER,
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    options_response,
)

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

VALID_THEMES = {"system", "light", "dark"}
VALID_ACCENTS = {"teal", "amber", "blue", "green", "violet", "rose", "graphite"}


class SettingsResponse(BaseModel):
    """Response for user settings."""

    default_language: str
    summary_language: str
    summary_style: str
    summary_instructions: str | None
    dictation_live_stt_provider: str
    dictation_live_stt_model: str
    recording_live_stt_provider: str
    recording_live_stt_model: str
    file_stt_provider: str
    file_stt_model: str
    dictation_post_filter_enabled: bool
    dictation_post_filter_provider: str
    dictation_post_filter_model: str
    region: str


VALID_REGIONS = {"global", "ru"}

MANAGED_TRANSCRIPTION_FIELDS = (
    "dictation_live_stt_provider",
    "dictation_live_stt_model",
    "recording_live_stt_provider",
    "recording_live_stt_model",
    "file_stt_provider",
    "file_stt_model",
    "dictation_post_filter_provider",
    "dictation_post_filter_model",
)


class UpdateSettingsRequest(BaseModel):
    """Request to update user settings."""

    default_language: str | None = None
    summary_language: str | None = None
    summary_style: str | None = None
    summary_instructions: str | None = None
    dictation_live_stt_provider: str | None = None
    dictation_live_stt_model: str | None = None
    recording_live_stt_provider: str | None = None
    recording_live_stt_model: str | None = None
    file_stt_provider: str | None = None
    file_stt_model: str | None = None
    dictation_post_filter_enabled: bool | None = None
    dictation_post_filter_provider: str | None = None
    dictation_post_filter_model: str | None = None
    region: str | None = None

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in VALID_REGIONS:
            raise ValueError(f"region must be one of: {', '.join(sorted(VALID_REGIONS))}")
        return normalized

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

    @field_validator(
        "dictation_live_stt_provider",
        "recording_live_stt_provider",
        "file_stt_provider",
        "dictation_post_filter_provider",
    )
    @classmethod
    def normalize_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider cannot be empty")
        return normalized

    @field_validator(
        "dictation_live_stt_model",
        "recording_live_stt_model",
        "file_stt_model",
        "dictation_post_filter_model",
    )
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("model cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_transcription_pairs(self) -> "UpdateSettingsRequest":
        pairs = (
            (
                "dictation_live_stt",
                self.dictation_live_stt_provider,
                self.dictation_live_stt_model,
            ),
            (
                "recording_live_stt",
                self.recording_live_stt_provider,
                self.recording_live_stt_model,
            ),
            ("file_stt", self.file_stt_provider, self.file_stt_model),
            (
                "dictation_post_filter",
                self.dictation_post_filter_provider,
                self.dictation_post_filter_model,
            ),
        )
        for group, provider, model in pairs:
            if (provider is None) != (model is None):
                raise ValueError(f"{group} provider and model must be updated together")
        return self

    @property
    def has_managed_transcription_patch(self) -> bool:
        return any(getattr(self, field) is not None for field in MANAGED_TRANSCRIPTION_FIELDS)


class TranscriptionOptionResponse(BaseModel):
    """One curated provider/model option exposed to clients."""

    provider: str
    model: str
    label: str
    description: str


class TranscriptionOptionsResponse(BaseModel):
    """Curated transcription settings options."""

    dictation_live_stt: list[TranscriptionOptionResponse]
    recording_live_stt: list[TranscriptionOptionResponse]
    file_stt: list[TranscriptionOptionResponse]
    dictation_post_filter: list[TranscriptionOptionResponse]


def _settings_response(user: CurrentUser) -> SettingsResponse:
    return SettingsResponse(
        default_language=user.default_language,
        summary_language=user.summary_language,
        summary_style=user.summary_style,
        summary_instructions=user.summary_instructions,
        dictation_live_stt_provider=DEFAULT_DICTATION_LIVE_STT_PROVIDER,
        dictation_live_stt_model=DEFAULT_DICTATION_LIVE_STT_MODEL,
        recording_live_stt_provider=DEFAULT_RECORDING_LIVE_STT_PROVIDER,
        recording_live_stt_model=DEFAULT_RECORDING_LIVE_STT_MODEL,
        file_stt_provider=DEFAULT_FILE_STT_PROVIDER,
        file_stt_model=DEFAULT_FILE_STT_MODEL,
        dictation_post_filter_enabled=user.dictation_post_filter_enabled,
        dictation_post_filter_provider=DEFAULT_DICTATION_POST_FILTER_PROVIDER,
        dictation_post_filter_model=DEFAULT_DICTATION_POST_FILTER_MODEL,
        region=user.region,
    )


@router.get("/transcription-options", response_model=TranscriptionOptionsResponse)
async def get_transcription_options(user: CurrentUser) -> TranscriptionOptionsResponse:
    """Get curated transcription provider/model options."""
    return TranscriptionOptionsResponse(
        **options_response(settings=get_app_settings(), configured_only=True)
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: CurrentUser,
) -> SettingsResponse:
    """Get user settings."""
    return _settings_response(user)


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    request: UpdateSettingsRequest,
    user: CurrentUser,
    db: Database,
) -> SettingsResponse:
    """Update user settings."""
    if request.has_managed_transcription_patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription models are managed by WaiComputer.",
        )
    if request.default_language is not None:
        user.default_language = request.default_language
    if request.summary_language is not None:
        user.summary_language = request.summary_language
    if request.summary_style is not None:
        user.summary_style = request.summary_style
    # summary_instructions: allow explicit empty string to clear
    if request.summary_instructions is not None:
        user.summary_instructions = request.summary_instructions or None
    if request.dictation_post_filter_enabled is not None:
        user.dictation_post_filter_enabled = request.dictation_post_filter_enabled
    if request.region is not None:
        user.region = request.region
    await db.flush()
    return _settings_response(user)


class PreferencesResponse(BaseModel):
    """Response for the appearance preferences endpoint."""

    theme: str
    accent: str


class UpdatePreferencesRequest(BaseModel):
    """Partial update of appearance preferences."""

    theme: str | None = None
    accent: str | None = None

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in VALID_THEMES:
            raise ValueError(f"theme must be one of: {', '.join(sorted(VALID_THEMES))}")
        return normalized

    @field_validator("accent")
    @classmethod
    def validate_accent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in VALID_ACCENTS:
            raise ValueError(f"accent must be one of: {', '.join(sorted(VALID_ACCENTS))}")
        return normalized


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(user: CurrentUser) -> PreferencesResponse:
    """Get appearance preferences (theme + accent) for the current user."""
    return PreferencesResponse(theme=user.theme, accent=user.accent)


@router.patch("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    request: UpdatePreferencesRequest,
    user: CurrentUser,
    db: Database,
) -> PreferencesResponse:
    """Update appearance preferences.

    Accepts a partial body; unknown values are rejected with 422.
    """
    if request.theme is not None:
        user.theme = request.theme
    if request.accent is not None:
        user.accent = request.accent
    await db.flush()
    return PreferencesResponse(theme=user.theme, accent=user.accent)


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
