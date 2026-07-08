"""Per-user media library preferences (cleanup schedule)."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer

from app.database import Base


class UserMediaPreferences(Base):
    __tablename__ = "user_media_preferences"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    cleanup_enabled = Column(Boolean, default=False, nullable=False)
    cleanup_retention_days = Column(Integer, default=30, nullable=False)
    cleanup_hour = Column(Integer, default=3, nullable=False)
    cleanup_minute = Column(Integer, default=0, nullable=False)
    last_cleanup_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
