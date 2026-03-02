"""Chat session and message models."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ChatSession(Base, UUIDMixin, TimestampMixin):
    """Chat session for conversational Q&A against recordings."""

    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(500))
    recording_ids: Mapped[list | None] = mapped_column(JSONB)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base, UUIDMixin, TimestampMixin):
    """Individual message in a chat session."""

    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_segment_ids: Mapped[list | None] = mapped_column(JSONB)
    source_recording_ids: Mapped[list | None] = mapped_column(JSONB)

    # Relationships
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")


# Import at bottom to avoid circular imports
from app.models.user import User  # noqa: E402
