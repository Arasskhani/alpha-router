"""Provider connections: model providers (OpenRouter, OpenAI, etc.) and web search providers.

``kind`` says which, and never changes after a connection is made: a model
connection's key is sent to a model provider and its models are synced; a web
search connection's key is sent only to that search service, for the chat's
Web Search tool. Every model-side query reads ``kind = 'models'`` only.
"""

import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base, MoneyUSD


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (CheckConstraint("kind IN ('models', 'web_search')", name="chk_connections_kind"),)

    id = Column(Integer, primary_key=True)
    #: ``models`` or ``web_search`` (app.services.connection_kinds); set when the connection is made.
    kind = Column(String(16), nullable=False, default="models", server_default="models", index=True)
    name = Column(String(128), nullable=False)
    provider_type = Column(String(64), nullable=False, index=True)  # openrouter, openai, anthropic, google, custom
    adapter_key = Column(String(64), nullable=True, index=True)
    api_key_encrypted = Column(Text, nullable=False)
    base_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True)
    #: Provider options that are not a key: a Google search engine id (cx), a SearXNG category. JSON, or null.
    config_json = Column(Text, nullable=True)
    #: Web search: the order the connections are tried in, lowest first.
    priority = Column(Integer, nullable=False, default=100, server_default="100")
    #: Web search: what one search costs, charged to the person's budget (0: free, as for SearXNG).
    price_per_request_usd = Column(MoneyUSD, nullable=False, default=0.0, server_default="0")

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
