"""Provider connections (OpenRouter, OpenAI, etc.)."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Connection(Base):
    __tablename__ = "connections"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    provider_type = Column(String(64), nullable=False, index=True)  # openrouter, openai, anthropic, google, custom
    api_key_encrypted = Column(Text, nullable=False)
    base_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True)

    # Scheduled model sync
    sync_enabled = Column(Boolean, default=True)
    sync_interval_hours = Column(Integer, default=6)
    last_sync_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    audit_logs = relationship("ConnectionAuditLog", back_populates="connection", cascade="all, delete-orphan")


class ConnectionAuditLog(Base):
    __tablename__ = "connection_audit_logs"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("connections.id", ondelete="CASCADE"), index=True, nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(32), nullable=False)
    changes_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    connection = relationship("Connection", back_populates="audit_logs")
