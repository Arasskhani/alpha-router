"""Normalized per-user chat storage (sessions, messages, folders, prefs)."""

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")

CHANNEL_KIND_AI = "ai"
CHANNEL_KIND_MEMBER = "member"
CHANNEL_KINDS = (CHANNEL_KIND_AI, CHANNEL_KIND_MEMBER)


def normalize_channel_kind(value: str | None) -> str:
    kind = (value or CHANNEL_KIND_AI).strip().lower()
    return kind if kind == CHANNEL_KIND_MEMBER else CHANNEL_KIND_AI


def is_member_channel(session: "ChatSession | None") -> bool:
    if session is None:
        return False
    return normalize_channel_kind(getattr(session, "channel_kind", None)) == CHANNEL_KIND_MEMBER


def ai_channel_filter():
    """Treat NULL as AI so rows from before the column still belong to Chats."""
    return or_(
        ChatSession.channel_kind == CHANNEL_KIND_AI,
        ChatSession.channel_kind.is_(None),
    )


class ChatFolder(Base):
    __tablename__ = "chat_folders"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name = Column(String(255), nullable=False)
    color = Column(String(32), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title = Column(String(512), nullable=False, default="New chat")
    folder_id = Column(
        String(36), ForeignKey("chat_folders.id", ondelete="SET NULL"), nullable=True
    )
    model_id = Column(String(512), nullable=False, default="")
    current_agent_id = Column(
        String(36),
        nullable=True,
        index=True,
    )
    current_agent_version_id = Column(
        String(36),
        nullable=True,
        index=True,
    )
    agent_selected_at = Column(DateTime, nullable=True)
    tools = Column(JsonDocument, nullable=False, default=dict)
    private_mode = Column(Boolean, nullable=False, default=False)
    title_locked = Column(Boolean, nullable=False, default=False)
    title_generated = Column(Boolean, nullable=False, default=False)
    tools_touched = Column(Boolean, nullable=False, default=False)
    message_count = Column(Integer, nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=1)
    project_id = Column(
        String(36),
        nullable=True,
        index=True,
    )
    channel_kind = Column(
        String(16),
        nullable=False,
        default=CHANNEL_KIND_AI,
        server_default=CHANNEL_KIND_AI,
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    archived_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "channel_kind IN ('ai', 'member')",
            name="chk_chat_sessions_channel_kind",
        ),
        Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),
        Index("ix_chat_sessions_project_updated", "project_id", "updated_at"),
        Index(
            "ix_chat_sessions_project_channel_updated",
            "project_id",
            "channel_kind",
            "updated_at",
        ),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True)
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    author_display_name = Column(String(255), nullable=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False, default="")
    sequence = Column(Integer, nullable=False)
    client_message_id = Column(String(64), nullable=True)
    agent_run_id = Column(
        String(36),
        nullable=True,
        index=True,
    )
    meta = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "sequence", name="ux_chat_messages_session_sequence"
        ),
        UniqueConstraint(
            "session_id", "client_message_id", name="ux_chat_messages_client_id"
        ),
        Index("ix_chat_messages_session_sequence", "session_id", "sequence"),
        Index("ix_chat_messages_created_at", "created_at"),
    )


class ChatMessageFeedback(Base):
    __tablename__ = "chat_message_feedback"

    id = Column(Integer, primary_key=True)
    message_id = Column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rating = Column(SmallInteger, nullable=False)
    reason = Column(String(64), nullable=True)
    output_kind = Column(String(16), nullable=False)
    model_id = Column(String(512), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="ux_chat_message_feedback_user"),
        Index("ix_chat_feedback_kind_model", "output_kind", "model_id"),
    )


class UserChatPrefs(Base):
    __tablename__ = "user_chat_prefs"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    prefs = Column(JsonDocument, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class UserMemory(Base):
    """Durable facts about the user for cross-session personalization."""

    __tablename__ = "user_memories"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    origin = Column(String(16), nullable=False, default="auto", server_default="auto")
    category = Column(String(32), nullable=False, default="other", server_default="other")
    sensitivity = Column(
        String(16), nullable=False, default="normal", server_default="normal"
    )
    confidence = Column(Float, nullable=False, default=0.5, server_default="0.5")
    salience = Column(Float, nullable=False, default=0.5, server_default="0.5")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, nullable=False, default=0, server_default="0")
    source_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_message_id = Column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_id = Column(
        String(36),
        ForeignKey("user_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    embedding_status = Column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    embedding_model = Column(String(255), nullable=True)
    embedding_dims = Column(Integer, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="ux_user_memories_user_hash"),
        Index("ix_user_memories_user_updated", "user_id", "updated_at"),
        Index(
            "ix_user_memories_user_enabled_salience",
            "user_id",
            "enabled",
            "salience",
        ),
        Index("ix_user_memories_embedding_status", "embedding_status"),
        Index("ix_user_memories_expires_at", "expires_at"),
        Index("ix_user_memories_deleted_at", "deleted_at"),
    )


class UserMemoryJob(Base):
    """Debounced per-session extraction job for automatic memory capture."""

    __tablename__ = "user_memory_jobs"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status = Column(String(16), nullable=False, default="pending")
    watermark_sequence = Column(Integer, nullable=False, default=0)
    extracted_sequence = Column(Integer, nullable=False, default=0)
    run_after = Column(DateTime, nullable=False, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    lease_expires_at = Column(DateTime, nullable=True)
    worker_id = Column(String(64), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_user_memory_jobs_status_run", "status", "run_after"),
        Index(
            "ux_user_memory_jobs_open",
            "user_id",
            "session_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'retry')"),
            postgresql_where=text("status IN ('pending', 'retry')"),
        ),
    )


class UserMemoryEvent(Base):
    """Append-only audit trail for memory mutations (no memory text)."""

    __tablename__ = "user_memory_events"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    memory_id = Column(
        String(36),
        ForeignKey("user_memories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(32), nullable=False)
    actor = Column(String(16), nullable=False, default="system")
    session_id = Column(String(36), nullable=True)
    detail = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_user_memory_events_created", "created_at"),)


class UserMemorySuppression(Base):
    """Blocks a deleted fact from being re-learned."""

    __tablename__ = "user_memory_suppressions"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content_hash = Column(String(64), nullable=False, index=True)
    vector_indexed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "content_hash", name="ux_user_memory_suppressions_user_hash"
        ),
        Index("ix_user_memory_suppressions_expires", "expires_at"),
    )
