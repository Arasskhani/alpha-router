"""Alpha Router gateway keys (admin) and per-user keys."""

import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class AlphaRouterApiKey(Base):
    """Admin-created keys exposing all enabled models to Open WebUI / other clients."""

    __tablename__ = "alpha_router_api_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False)
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    credit_limit_usd = Column(Float, default=0.0)
    reset_period = Column(String(16), default="monthly")  # daily | weekly | monthly
    expires_at = Column(DateTime, nullable=True)
    period_used_usd = Column(Float, default=0.0)
    total_used_usd = Column(Float, default=0.0)
    period_started_at = Column(DateTime, nullable=True)

    owner = relationship("User", foreign_keys=[owner_user_id])
    audit_logs = relationship("AlphaRouterApiKeyAuditLog", back_populates="api_key", cascade="all, delete-orphan")


class AlphaRouterApiKeyAuditLog(Base):
    """Who changed a gateway API key and which fields changed."""

    __tablename__ = "alpha_router_api_key_audit_logs"

    id = Column(Integer, primary_key=True)
    alpha_router_api_key_id = Column(Integer, ForeignKey("alpha_router_api_keys.id", ondelete="CASCADE"), index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(32), nullable=False)
    changes_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    api_key = relationship("AlphaRouterApiKey", back_populates="audit_logs")
    actor = relationship("User", foreign_keys=[actor_user_id])


class UserApiKey(Base):
    """User-owned keys; usage debits the user's monthly budget."""

    __tablename__ = "user_api_keys"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name = Column(String(128), nullable=False)
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="user_api_keys")
