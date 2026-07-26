"""Per-user third-party connector credentials and OAuth tokens.

Each row binds a user to one connector (e.g. ``gmail``) and stores the
user-supplied OAuth client credentials plus the access/refresh tokens
obtained after the OAuth dance. All secrets are Fernet-encrypted at rest
via :mod:`app.services.secret_crypto`.
"""

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class UserConnector(Base):
    __tablename__ = "user_connectors"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_id", name="uq_user_connectors_user_provider"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(String(64), nullable=False, index=True)

    # User-supplied OAuth client credentials (encrypted at rest).
    client_id_encrypted = Column(Text, nullable=True)
    client_secret_encrypted = Column(Text, nullable=True)

    # Tokens obtained from the provider after the OAuth dance (encrypted at rest).
    access_token_encrypted = Column(Text, nullable=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    scope = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", backref="user_connectors")
