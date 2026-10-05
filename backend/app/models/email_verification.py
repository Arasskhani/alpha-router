"""One emailed code: to create an account, or to reset a forgotten password.

The person asks with their email address and gets a 6-digit code by email;
the browser keeps an opaque ``token`` that names this row. The code itself is
never stored - only an HMAC of it, keyed with the application secret and
bound to the token - so a copy of the table does not give codes away.

A row is good for one use: a few wrong tries, its expiry, or a newer request
for the same address and purpose end it (``consumed_at``). Rows are small and
short-lived; old ones are removed when new ones are made.
"""

from __future__ import annotations

import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String

from app.database import Base

PURPOSE_SIGNUP = "signup"
PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSES: tuple[str, ...] = (PURPOSE_SIGNUP, PURPOSE_PASSWORD_RESET)


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    __table_args__ = (
        CheckConstraint("purpose IN ('signup', 'password_reset')", name="chk_email_verifications_purpose"),
        Index("ix_email_verifications_email_purpose", "email", "purpose", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    #: What the browser holds between the steps; never in a URL.
    token = Column(String(64), nullable=False, unique=True)
    purpose = Column(String(16), nullable=False)
    #: Lowercased.
    email = Column(String(255), nullable=False)
    #: The account a reset is for; none for a sign-up.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    code_hash = Column(String(64), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    ip = Column(String(64), nullable=True)
