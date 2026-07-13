"""Normalized per-user chat storage (sessions, messages, folders, prefs)."""

import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class ChatFolder(Base):
    __tablename__ = "chat_folders"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    color = Column(String(32), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title = Column(String(512), nullable=False, default="New chat")
    folder_id = Column(String(36), ForeignKey("chat_folders.id", ondelete="SET NULL"), nullable=True)
    model_id = Column(String(512), nullable=False, default="")
    tools = Column(JsonDocument, nullable=False, default=dict)
    private_mode = Column(Boolean, nullable=False, default=False)
    title_locked = Column(Boolean, nullable=False, default=False)
    title_generated = Column(Boolean, nullable=False, default=False)
    tools_touched = Column(Boolean, nullable=False, default=False)
    message_count = Column(Integer, nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    archived_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False, default="")
    sequence = Column(Integer, nullable=False)
    client_message_id = Column(String(64), nullable=True)
    meta = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="ux_chat_messages_session_sequence"),
        UniqueConstraint("session_id", "client_message_id", name="ux_chat_messages_client_id"),
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
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
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

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    prefs = Column(JsonDocument, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
