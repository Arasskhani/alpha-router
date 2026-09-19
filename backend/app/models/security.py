"""TLS certificates, admin IP allowlist, and security audit events."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

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
    """One administrative action, recorded so it can be answered for later.

    ``actor_username`` and ``actor_email`` are copies, not joins, and that is
    the point. ``actor_user_id`` is a foreign key with ``ON DELETE SET NULL``,
    so permanently deleting an administrator used to anonymise every action
    they had ever taken - the trail survived, but "who" did not. An audit row
    has to keep its meaning after the account it names is gone, so the identity
    is written onto the row at the time of the event.
    """

    __tablename__ = "security_audit_events"
    __table_args__ = (
        # The viewer filters on actor and on action, and neither had an index:
        # every filtered page was a sequential scan of the whole table.
        Index("ix_security_audit_events_actor_created", "actor_user_id", "created_at"),
        Index("ix_security_audit_events_action_created", "action", "created_at"),
        # The filter panel runs SELECT DISTINCT over these two as well, and
        # neither had anything to read but the heap.
        Index("ix_security_audit_events_resource_type", "resource_type"),
        Index("ix_security_audit_events_actor_username", "actor_username"),
    )

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_username = Column(String(255), nullable=True)
    actor_email = Column(String(255), nullable=True)
    actor_ip = Column(String(64), nullable=True)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(64), nullable=True)
    detail_json = Column(Text, nullable=True)
    #: Set when retention has blanked detail_json, so the UI can say the row was
    #: redacted rather than leaving the operator wondering where the detail went.
    detail_redacted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
