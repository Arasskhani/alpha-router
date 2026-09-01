"""TLS certificates, admin IP allowlist, and security audit events."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class AdminIpAllowlistEntry(Base):
    __tablename__ = "admin_ip_allowlist_entries"

    id = Column(Integer, primary_key=True)
    cidr = Column(String(64), nullable=False)
    label = Column(String(128), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class TlsCertificate(Base):
    __tablename__ = "tls_certificates"

    id = Column(Integer, primary_key=True)
    label = Column(String(128), nullable=False)
    cert_pem = Column(Text, nullable=False)
    key_pem_encrypted = Column(Text, nullable=False)
    chain_pem = Column(Text, nullable=True)
    subject = Column(String(512), nullable=True)
    sans_json = Column(Text, nullable=True)
    issuer = Column(String(512), nullable=True)
    serial = Column(String(128), nullable=True)
    not_before = Column(DateTime, nullable=True)
    not_after = Column(DateTime, nullable=True)
    sha256_fingerprint = Column(String(64), nullable=False)
    key_algorithm = Column(String(32), nullable=True)
    key_bits = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_ip = Column(String(64), nullable=True)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(64), nullable=True)
    detail_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
