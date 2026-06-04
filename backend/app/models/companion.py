"""Companion (Wai chat) models: conversations, messages, citations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Conversation(Base, UUIDMixin, TimestampMixin):
    """A Wai chat session — a thread of multi-turn messages with the user."""

    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(500))
    # scope: {recording_ids?, folder_ids?, types?, speakers?, date_from?, date_to?}
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base, UUIDMixin):
    """A single message in a conversation (user, assistant, or tool result).

    Messages are immutable once written, with ONE exception: an assistant
    message's ``content``/usage/``status`` are updated in place while its turn
    is streaming (``status='streaming'``) and finalized when the turn completes
    or fails. This durability lets a dropped SSE stream resume from the
    persisted partial instead of losing the turn. No TimestampMixin:
    ``created_at`` is the only timestamp.
    """

    __tablename__ = "chat_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'user' | 'assistant' | 'tool'
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Assistant-turn lifecycle: 'streaming' while in flight, 'complete' once
    # finalized, 'failed' if the turn errored. User/tool messages are always
    # 'complete'. The only mutable field on a message (see class docstring).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="complete"
    )
    # OpenAI Responses API content blocks
    content: Mapped[list[Any] | dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Raw tool_use blocks for replay/eval — only set on assistant messages
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSONB)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    citations: Mapped[list["MessageCitation"]] = relationship(
        "MessageCitation",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageCitation.citation_index",
    )


class MessageCitation(Base, UUIDMixin):
    """A citation linking a span of an assistant message to a transcript segment."""

    __tablename__ = "message_citations"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL so deleting a segment/recording doesn't break chat history.
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="SET NULL"),
        nullable=True,
    )
    span_start: Mapped[int] = mapped_column(Integer, nullable=False)
    span_end: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    message: Mapped["ChatMessage"] = relationship(
        "ChatMessage", back_populates="citations"
    )
