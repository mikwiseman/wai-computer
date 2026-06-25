"""Recording and related models."""

import enum
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.person import Person


class RecordingStatus(str, enum.Enum):
    """Lifecycle states for recording upload and processing."""

    PENDING_UPLOAD = "pending_upload"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


ACTIVE_RECORDING_STATUSES = frozenset(
    {
        RecordingStatus.PENDING_UPLOAD.value,
        RecordingStatus.UPLOADING.value,
        RecordingStatus.PROCESSING.value,
    }
)


class SummaryGenerationStatus(str, enum.Enum):
    """Lifecycle states for manual summary generation jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Folder(Base, UUIDMixin, TimestampMixin):
    """Folder for organizing recordings."""

    __tablename__ = "folders"
    # Note: unique constraint on (user_id, name) deferred — migration 000010 removed
    # due to production deploy issues. Will re-add with proper pre-validation.

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="folders")
    recordings: Mapped[list["Recording"]] = relationship("Recording", back_populates="folder")


class Recording(Base, UUIDMixin, TimestampMixin):
    """Audio recording model."""

    __tablename__ = "recordings"
    # RETURNING-fetch server defaults (e.g. updated_at onupdate) on flush so the
    # ORM object isn't left with an expired attribute that a sync serializer would
    # try to lazy-load (MissingGreenlet) after an UPDATE.
    __mapper_args__ = {"eager_defaults": True}

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(500))
    # True while the title is auto-generated (provisional or summary-derived); a
    # user rename flips it False so the authoritative summary title never clobbers
    # a manual one. See apply_summary_result + update_recording.
    title_auto_generated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # meeting, note, reflection
    audio_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RecordingStatus.PENDING_UPLOAD.value,
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    billed_word_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    language: Mapped[str | None] = mapped_column(String(10))
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    starred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Trust/salience signals for the P4 ranking multiplier (neutral defaults).
    authority_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.5", default=0.5
    )
    salience_score: Mapped[float | None] = mapped_column(Float)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="recordings")
    folder: Mapped["Folder | None"] = relationship("Folder", back_populates="recordings")
    segments: Mapped[list["Segment"]] = relationship(
        "Segment", back_populates="recording", cascade="all, delete-orphan"
    )
    summary: Mapped["Summary | None"] = relationship(
        "Summary", back_populates="recording", cascade="all, delete-orphan", uselist=False
    )
    summary_generation_jobs: Mapped[list["SummaryGenerationJob"]] = relationship(
        "SummaryGenerationJob",
        back_populates="recording",
        cascade="all, delete-orphan",
        order_by="desc(SummaryGenerationJob.created_at)",
    )
    summary_audio_artifacts: Mapped[list["SummaryAudioArtifact"]] = relationship(
        "SummaryAudioArtifact",
        back_populates="recording",
        cascade="all, delete-orphan",
        order_by="desc(SummaryAudioArtifact.created_at)",
    )
    action_items: Mapped[list["ActionItem"]] = relationship(
        "ActionItem", back_populates="recording", cascade="all, delete-orphan"
    )
    tags: Mapped[list["RecordingTag"]] = relationship(
        "RecordingTag", back_populates="recording", cascade="all, delete-orphan"
    )
    highlights: Mapped[list["Highlight"]] = relationship(
        "Highlight", back_populates="recording", cascade="all, delete-orphan"
    )
    share_links: Mapped[list["RecordingShare"]] = relationship(
        "RecordingShare", back_populates="recording", cascade="all, delete-orphan"
    )


class RecordingShare(Base, UUIDMixin, TimestampMixin):
    """Public share link for a recording.

    Only a SHA-256 hash of the bearer token is stored. The raw token is returned
    once when the owner creates a share link and is later verified by hashing the
    token from the public URL.
    """

    __tablename__ = "recording_shares"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    recording: Mapped["Recording"] = relationship("Recording", back_populates="share_links")


class Segment(Base, UUIDMixin):
    """Transcript segment with speaker diarization."""

    __tablename__ = "segments"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    speaker: Mapped[str | None] = mapped_column(String(100))
    raw_label: Mapped[str | None] = mapped_column(String(100))
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    auto_assigned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    match_confidence: Mapped[float | None] = mapped_column(Float)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    # Relationships
    recording: Mapped["Recording"] = relationship("Recording", back_populates="segments")
    person: Mapped["Person | None"] = relationship("Person")


class Summary(Base, UUIDMixin, TimestampMixin):
    """AI-generated summary of a recording."""

    __tablename__ = "summaries"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[list | None] = mapped_column(JSONB)
    decisions: Mapped[list | None] = mapped_column(JSONB)
    topics: Mapped[list | None] = mapped_column(JSONB)
    people_mentioned: Mapped[list | None] = mapped_column(JSONB)
    sentiment: Mapped[str | None] = mapped_column(String(20))

    # Relationships
    recording: Mapped["Recording"] = relationship("Recording", back_populates="summary")


class SummaryGenerationJob(Base, UUIDMixin, TimestampMixin):
    """Durable server-side state for manual summary generation."""

    __tablename__ = "summary_generation_jobs"
    __table_args__ = (
        Index("ix_summary_generation_jobs_recording_id", "recording_id"),
        Index("ix_summary_generation_jobs_user_id", "user_id"),
        Index("ix_summary_generation_jobs_status", "status"),
        Index(
            "ux_summary_generation_jobs_active_recording",
            "recording_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SummaryGenerationStatus.QUEUED.value,
        server_default=SummaryGenerationStatus.QUEUED.value,
    )
    stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    transcript_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    instructions_override: Mapped[str | None] = mapped_column(Text)
    task_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    recording: Mapped["Recording"] = relationship(
        "Recording",
        back_populates="summary_generation_jobs",
    )
    user: Mapped["User"] = relationship("User")


class ActionItem(Base, UUIDMixin, TimestampMixin):
    """Action item extracted from a recording."""

    __tablename__ = "action_items"

    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str | None] = mapped_column(String(20))  # high, medium, low
    status: Mapped[str] = mapped_column(String(20), default="pending")
    source: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)

    # Relationships
    recording: Mapped["Recording"] = relationship("Recording", back_populates="action_items")


# Import at bottom to avoid circular imports
from app.models.entity import RecordingTag  # noqa: E402
from app.models.highlight import Highlight  # noqa: E402
from app.models.summary_audio import SummaryAudioArtifact  # noqa: E402
from app.models.user import User  # noqa: E402
