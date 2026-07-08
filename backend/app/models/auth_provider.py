"""LDAP / Keycloak configuration stored in database (admin UI)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.database import Base


class AuthProviderConfig(Base):
    __tablename__ = "auth_providers"

    provider = Column(String(32), primary_key=True)  # ldap | keycloak
    enabled = Column(Boolean, default=False)
    config_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
