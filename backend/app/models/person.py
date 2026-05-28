"""Person and Voiceprint models for editable speaker identification."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Person(Base, UUIDMixin, TimestampMixin):
    """A known speaker in the user's address book."""

    __tablename__ = "people"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20))
    aliases: Mapped[list | None] = mapped_column(JSONB)

    user: Mapped["User"] = relationship("User", back_populates="people")
    voiceprints: Mapped[list["Voiceprint"]] = relationship(
        "Voiceprint", back_populates="person", cascade="all, delete-orphan"
    )


class Voiceprint(Base, UUIDMixin, TimestampMixin):
    """A single voice embedding sample attached to a Person.

    Multiple voiceprints per Person — match by max cosine similarity, not by averaging.
    """

    __tablename__ = "voiceprints"

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(192), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    source_recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recordings.id", ondelete="SET NULL")
    )
    source_raw_label: Mapped[str | None] = mapped_column(String(100))
    duration_s: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)

    person: Mapped["Person"] = relationship("Person", back_populates="voiceprints")


class RecordingSpeakerEmbedding(Base, UUIDMixin, TimestampMixin):
    """A transient recording diarization cluster embedding retained for speaker learning.

    This is not a named speaker by itself. It lets a later manual assignment
    promote the cluster into a Person voiceprint and lets rematch run without
    retaining the source audio file.
    """

    __tablename__ = "recording_speaker_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "recording_id",
            "raw_label",
            "model",
            name="uq_recording_speaker_embeddings_recording_raw_model",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_label: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(192), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)


# Import at bottom to avoid circular imports
from app.models.user import User  # noqa: E402,F401
