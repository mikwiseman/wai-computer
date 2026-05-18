"""Dictation history and dictionary models.

Server-side mirror of the macOS client's local dictation log and custom
vocabulary. Stored under `user_id` so history survives logout/login and
syncs across Macs. The `client_*_id` columns are the client-generated
UUIDs used as idempotency keys for POST retries.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DictationEntry(Base, UUIDMixin, TimestampMixin):
    """A single dictation event captured on a client."""

    __tablename__ = "dictation_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    user: Mapped["User"] = relationship("User", back_populates="dictation_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "client_entry_id", name="uq_dictation_entries_user_client_id"),
    )


class DictationDictionaryWord(Base, UUIDMixin, TimestampMixin):
    """A user-curated vocabulary word or replacement rule."""

    __tablename__ = "dictation_dictionary_words"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_word_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    word: Mapped[str] = mapped_column(String(200), nullable=False)
    replacement: Mapped[str | None] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="dictation_dictionary_words")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_word_id", name="uq_dictation_dictionary_user_client_id"
        ),
    )


# Avoid circular import.
from app.models.user import User  # noqa: E402
