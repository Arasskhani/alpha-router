"""One row per sign-in, failed attempt, sign-out and session revocation.

These used to be three ``action`` values in ``security_audit_events``, with the
reason for a failure inside ``detail_json``. That table is the right place for
"an administrator changed a setting"; it is the wrong shape for authentication:

* ``detail_json`` is text, so filtering by outcome or reason meant parsing JSON
  in Python — and retention blanks it on a shorter window than the row, so the
  reason a login failed aged out before the fact that it failed.
* Nothing distinguished "signed out" from "every session was revoked because
  the password changed", which an administrator reads very differently.
* Half the paths that end a session never wrote anything at all.

Every column here is the essential fact; nothing on this table is redacted.
The row keeps ``username`` as a snapshot because ``user_id`` is
``ON DELETE SET NULL`` and an audit record has to keep its meaning after the
account it names is gone.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.database import Base

#: ``event_type`` values. ``session_revoked`` is the one that did not exist
#: before: a sign-out the person did not perform, caused by a password change,
#: an administrator's reset, deactivation or deletion.
EVENT_LOGIN_SUCCESS = "login_success"
EVENT_LOGIN_FAILED = "login_failed"
EVENT_LOGIN_RATE_LIMITED = "login_rate_limited"
EVENT_LOGOUT = "logout"
EVENT_SESSION_REVOKED = "session_revoked"
EVENT_TYPES: tuple[str, ...] = (
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_RATE_LIMITED,
    EVENT_LOGOUT,
    EVENT_SESSION_REVOKED,
)

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
#: Sign-outs and revocations are neither a success nor a failure of a sign-in.
OUTCOME_NONE = "n/a"

#: A sign-out in this product bumps ``users.token_version`` and therefore ends
#: every session on every device. Recording that honestly is what stops the UI
#: from pretending a logout row pairs with exactly one login row.
SCOPE_THIS_SESSION = "this_session"
SCOPE_ALL_SESSIONS = "all_sessions"

AUTH_METHODS: tuple[str, ...] = ("local", "ldap", "saml", "oidc")

#: Stable codes; the UI owns the human labels. Adding one here is a product
#: decision, so the allowed set is a tuple rather than free text.
REASON_CODES: tuple[str, ...] = (
    # login_failed
    "bad_password",
    "no_such_user",
    "account_inactive",
    "account_deleted",
    "twofa_required",
    "twofa_failed",
    "ldap_unavailable",
    "ldap_rejected",
    "saml_rejected",
    "oidc_rejected",
    "sso_code_invalid",
    "unknown",
    # login_rate_limited
    "rate_limited",
    # session_revoked
    "password_changed",
    "admin_password_reset",
    "admin_2fa_disabled",
    "user_deactivated",
    "user_deleted",
)

REASON_DETAIL_MAX_CHARS = 2000
USER_AGENT_MAX_CHARS = 512


class AuthEvent(Base):
    __tablename__ = "auth_events"
    __table_args__ = (
        Index("ix_auth_events_user_time", "user_id", "occurred_at"),
        Index("ix_auth_events_ip_time", "ip", "occurred_at"),
        Index("ix_auth_events_type_time", "event_type", "occurred_at"),
        Index("ix_auth_events_outcome_time", "outcome", "occurred_at"),
        # Backfill idempotency: one row per legacy audit event, ever.
        Index("ux_auth_events_source_event", "source_event_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    occurred_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = Column(String(255), nullable=True)
    event_type = Column(String(32), nullable=False)
    outcome = Column(String(16), nullable=False)
    scope = Column(String(16), nullable=True)
    reason_code = Column(String(48), nullable=True)
    reason_detail = Column(Text, nullable=True)
    auth_method = Column(String(16), nullable=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(USER_AGENT_MAX_CHARS), nullable=True)
    session_id = Column(String(36), nullable=True)
    correlation_id = Column(String(64), nullable=True)
    source_event_id = Column(Integer, nullable=True)
    backfilled = Column(Boolean, nullable=False, default=False)
