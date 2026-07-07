"""User model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
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
    __table_args__ = (
        # Real emails stay unique; Telegram-only accounts have NULL email and may
        # coexist (a partial unique index, not a full UNIQUE constraint).
        Index(
            "uq_users_email_not_null",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
    )

    # NULL for Telegram-only accounts (keyed by telegram_user_id); set when the
    # user opts to add an email for web login / receipts / recovery.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Where the account was created: web | magic | telegram (analytics + recovery).
    signup_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Public identity. Both are user-managed in Settings and stay NULL by default;
    # the voice-sharing directory feature surfaces them to other users only when
    # the user explicitly opts in.
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Pointer to the user's own Person row, set on first voice enrollment so
    # downstream features (directory publish, "you" display, name parsing)
    # always know which Person represents self without guessing by display_name.
    self_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )
    magic_link_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    magic_link_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Brain feed watermark — when the user last opened the Brain (P0b "since you
    # last looked").
    brain_last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    dictation_cleanup_level: Mapped[str] = mapped_column(
        String(20),
        default="none",
        server_default="none",
        nullable=False,
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
    # Personal style rules injected into dictation cleanup ("never use the
    # word utilize", "always capitalize API"). Style-only by prompt contract.
    dictation_style_rules: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Billing region — seeded from WAIDownloadRegion at signup (global|ru).
    # Drives default payment provider; user can override in Settings.
    region: Mapped[str] = mapped_column(
        String(10), default="global", server_default="global", nullable=False
    )

    # UI appearance preferences — synced from the web ThemeAccentPicker.
    # theme: system | light | dark. accent: teal | amber | blue | green | violet | rose | graphite.
    theme: Mapped[str] = mapped_column(
        String(10), default="system", server_default="system", nullable=False
    )
    accent: Mapped[str] = mapped_column(
        String(12), default="teal", server_default="teal", nullable=False
    )
    account_status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False, index=True
    )
    account_status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_status_changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    # Convenience pointer to the active subscription. NULL = free tier.
    current_subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    # Stripe Customer object id (`cus_...`) — set lazily the first time we open
    # the Customer Portal or run checkout. Lets us drive the portal session and
    # `stripe.Invoice.list(customer=…)` without depending on an active Subscription.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

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
    dictation_snippets: Mapped[list["DictationSnippet"]] = relationship(
        "DictationSnippet", back_populates="user", cascade="all, delete-orphan"
    )
    personalization_terms: Mapped[list["PersonalizationTerm"]] = relationship(
        "PersonalizationTerm", back_populates="user", cascade="all, delete-orphan"
    )
    personalization_import_jobs: Mapped[list["PersonalizationImportJob"]] = relationship(
        "PersonalizationImportJob", back_populates="user", cascade="all, delete-orphan"
    )
    people: Mapped[list["Person"]] = relationship(
        "Person",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Person.user_id",
    )


# Import at bottom to avoid circular imports
from app.models.dictation import (  # noqa: E402
    DictationDictionaryWord,
    DictationEntry,
    DictationSnippet,
)
from app.models.entity import Entity, Tag  # noqa: E402
from app.models.person import Person  # noqa: E402
from app.models.personalization import PersonalizationImportJob, PersonalizationTerm  # noqa: E402
from app.models.recording import Folder, Recording  # noqa: E402
