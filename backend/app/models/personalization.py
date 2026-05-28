"""User personalization models."""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class PersonalizationImportJob(Base, UUIDMixin, TimestampMixin):
    """Imported text bundle used to extract user-specific terminology."""

    __tablename__ = "personalization_import_jobs"
    __table_args__ = (
        Index("ix_personalization_import_jobs_user_id", "user_id"),
        Index("ix_personalization_import_jobs_status", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="personalization_import_jobs")
    terms: Mapped[list["PersonalizationTerm"]] = relationship(
        "PersonalizationTerm",
        back_populates="import_job",
        cascade="all, delete-orphan",
    )


class PersonalizationTerm(Base, UUIDMixin, TimestampMixin):
    """User-approved or pending term used by transcription and summarization."""

    __tablename__ = "personalization_terms"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "normalized_term",
            name="uq_personalization_terms_user_normalized_term",
        ),
        Index("ix_personalization_terms_user_status", "user_id", "status"),
        Index("ix_personalization_terms_import_job_id", "import_job_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personalization_import_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_term: Mapped[str] = mapped_column(String(200), nullable=False)
    replacement: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    user: Mapped["User"] = relationship("User", back_populates="personalization_terms")
    import_job: Mapped["PersonalizationImportJob | None"] = relationship(
        "PersonalizationImportJob",
        back_populates="terms",
    )


from app.models.user import User  # noqa: E402
