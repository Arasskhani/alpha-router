"""The browser extension: the browsers a user connected, and what the extension did.

``extension_sessions`` holds one row per connected browser. Its tokens are
opaque random strings stored only as SHA-256 hashes, never JWTs: a session JWT
is checked for its signature and nothing else, so an extension token in that
shape could be replayed as a session cookie. The access token lives an hour;
the refresh token rotates, and a rotated one presented after a short grace is
a sign of theft that ends the session. ``token_version`` is the user's at the
time of connecting, so a sign-out everywhere ends extension sessions too.

``extension_events`` is the extension's audit trail for Admin Logs: a page
shared with a model (the site, how much text, which model - never the text)
and each step the browser agent takes (the tool, the site, what happened and
who approved it). It has the same two retention windows as the security trail:
the detail is blanked first, the row goes later.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.database import Base

DEVICE_NAME_MAX_CHARS = 64
USER_AGENT_MAX_CHARS = 255


class ExtensionSession(Base):
    """One browser a user connected the extension from."""

    __tablename__ = "extension_sessions"
    __table_args__ = (
        Index("ux_extension_sessions_access_token", "access_token_hash", unique=True),
        Index("ux_extension_sessions_refresh_token", "refresh_token_hash", unique=True),
        Index("ix_extension_sessions_prior_refresh", "prior_refresh_token_hash"),
        Index("ix_extension_sessions_user", "user_id"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_name = Column(String(DEVICE_NAME_MAX_CHARS), nullable=False, default="")
    access_token_hash = Column(String(64), nullable=False)
    access_expires_at = Column(DateTime, nullable=False)
    refresh_token_hash = Column(String(64), nullable=False)
    prior_refresh_token_hash = Column(String(64), nullable=True)
    prior_refresh_valid_until = Column(DateTime, nullable=True)
    refresh_expires_at = Column(DateTime, nullable=False)
    absolute_expires_at = Column(DateTime, nullable=False)
    token_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    last_ip = Column(String(64), nullable=True)
    user_agent = Column(String(USER_AGENT_MAX_CHARS), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(32), nullable=True)


class ExtensionEvent(Base):
    """A page shared with a model, or a step of the browser agent."""

    __tablename__ = "extension_events"
    __table_args__ = (
        Index("ix_extension_events_created_at", "created_at"),
        Index("ix_extension_events_actor_time", "actor_user_id", "created_at"),
        Index("ix_extension_events_session", "session_id"),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: Copied, so the row keeps its meaning after the account is purged.
    actor_username = Column(String(255), nullable=True)
    actor_ip = Column(String(64), nullable=True)
    session_id = Column(String(36), nullable=True)
    #: page_context | agent_step | agent_task
    kind = Column(String(32), nullable=False)
    #: The host only, never a full URL.
    site = Column(String(255), nullable=True)
    action = Column(String(64), nullable=True)
    outcome = Column(String(16), nullable=True)
    detail_json = Column(Text, nullable=False, default="{}")
    detail_redacted_at = Column(DateTime, nullable=True)
