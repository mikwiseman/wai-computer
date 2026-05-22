"""User model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.transcription_options import (
    DEFAULT_DICTATION_LIVE_STT_MODEL,
    DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    DEFAULT_DICTATION_POST_FILTER_MODEL,
    DEFAULT_DICTATION_POST_FILTER_PROVIDER,
    DEFAULT_FILE_STT_MODEL,
    DEFAULT_FILE_STT_PROVIDER,
    DEFAULT_RECORDING_LIVE_STT_MODEL,
    DEFAULT_RECORDING_LIVE_STT_PROVIDER,
)
from app.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """User account model."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    default_language: Mapped[str] = mapped_column(
        String(10), default="multi", server_default="multi"
    )
    summary_language: Mapped[str] = mapped_column(
        String(10), default="auto", server_default="auto"
    )
    summary_style: Mapped[str] = mapped_column(
        String(20), default="medium", server_default="medium"
    )
    summary_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    dictation_live_stt_provider: Mapped[str] = mapped_column(
        String(40),
        default=DEFAULT_DICTATION_LIVE_STT_PROVIDER,
        server_default=DEFAULT_DICTATION_LIVE_STT_PROVIDER,
    )
    dictation_live_stt_model: Mapped[str] = mapped_column(
        String(100),
        default=DEFAULT_DICTATION_LIVE_STT_MODEL,
        server_default=DEFAULT_DICTATION_LIVE_STT_MODEL,
    )
    recording_live_stt_provider: Mapped[str] = mapped_column(
        String(40),
        default=DEFAULT_RECORDING_LIVE_STT_PROVIDER,
        server_default=DEFAULT_RECORDING_LIVE_STT_PROVIDER,
    )
    recording_live_stt_model: Mapped[str] = mapped_column(
        String(100),
        default=DEFAULT_RECORDING_LIVE_STT_MODEL,
        server_default=DEFAULT_RECORDING_LIVE_STT_MODEL,
    )
    file_stt_provider: Mapped[str] = mapped_column(
        String(40),
        default=DEFAULT_FILE_STT_PROVIDER,
        server_default=DEFAULT_FILE_STT_PROVIDER,
    )
    file_stt_model: Mapped[str] = mapped_column(
        String(100),
        default=DEFAULT_FILE_STT_MODEL,
        server_default=DEFAULT_FILE_STT_MODEL,
    )
    dictation_post_filter_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
    )
    dictation_post_filter_provider: Mapped[str] = mapped_column(
        String(40),
        default=DEFAULT_DICTATION_POST_FILTER_PROVIDER,
        server_default=DEFAULT_DICTATION_POST_FILTER_PROVIDER,
    )
    dictation_post_filter_model: Mapped[str] = mapped_column(
        String(100),
        default=DEFAULT_DICTATION_POST_FILTER_MODEL,
        server_default=DEFAULT_DICTATION_POST_FILTER_MODEL,
    )

    # Billing region — seeded from WAIDownloadRegion at signup (global|ru).
    # Drives default payment provider; user can override in Settings.
    region: Mapped[str] = mapped_column(
        String(10), default="global", server_default="global", nullable=False
    )
    # Convenience pointer to the active subscription. NULL = free tier.
    current_subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    # Legal acceptance captured at account creation or password completion.
    legal_terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legal_privacy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legal_acceptance_locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    legal_acceptance_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    recordings: Mapped[list["Recording"]] = relationship(
        "Recording", back_populates="user", cascade="all, delete-orphan"
    )
    folders: Mapped[list["Folder"]] = relationship(
        "Folder", back_populates="user", cascade="all, delete-orphan"
    )
    entities: Mapped[list["Entity"]] = relationship(
        "Entity", back_populates="user", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="user", cascade="all, delete-orphan"
    )
    dictation_entries: Mapped[list["DictationEntry"]] = relationship(
        "DictationEntry", back_populates="user", cascade="all, delete-orphan"
    )
    dictation_dictionary_words: Mapped[list["DictationDictionaryWord"]] = relationship(
        "DictationDictionaryWord", back_populates="user", cascade="all, delete-orphan"
    )
    people: Mapped[list["Person"]] = relationship(
        "Person", back_populates="user", cascade="all, delete-orphan"
    )


# Import at bottom to avoid circular imports
from app.models.dictation import DictationDictionaryWord, DictationEntry  # noqa: E402
from app.models.entity import Entity, Tag  # noqa: E402
from app.models.person import Person  # noqa: E402
from app.models.recording import Folder, Recording  # noqa: E402
