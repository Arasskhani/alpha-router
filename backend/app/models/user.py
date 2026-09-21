"""User accounts, RBAC, and directory profile fields."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.database import Base, MoneyUSD

JsonDocument = JSON().with_variant(JSONB(), "postgresql")

user_group_members = Table(
    "user_group_members",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
)


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_slug = Column(String(64), primary_key=True)


class UserGroup(Base):
    __tablename__ = "user_groups"
    __table_args__ = (UniqueConstraint("name", "source", name="uq_group_name_source"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, index=True)
    description = Column(Text, nullable=True)
    # local | ldap | saml
    source = Column(String(32), default="local", index=True)
    external_id = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    members = relationship("User", secondary=user_group_members, back_populates="groups")
    plan_assignments = relationship("PlanAssignment", back_populates="group")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    display_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)

    auth_provider = Column(String(32), default="local")  # local | ldap | saml
    external_id = Column(String(255), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    # Monotonic counter bumped to revoke all previously-issued JWTs for this
    # user (on logout, password reset, admin disable). The JWT carries the
    # value at issue time as ``ver``; a request is rejected when
    # ``jwt.ver < user.token_version``.
    token_version = Column(Integer, nullable=False, server_default="0", default=0)

    # Directory / HR fields for reporting filters
    company = Column(String(255), nullable=True)
    job_title = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True, index=True)
    office = Column(String(255), nullable=True)
    reporting_to = Column(String(255), nullable=True)

    # Budget: resolved from plan assignment; cached monthly remaining
    monthly_budget_usd = Column(MoneyUSD, default=0.0)
    budget_used_usd = Column(MoneyUSD, default=0.0)
    budget_reserved_usd = Column(MoneyUSD, nullable=False, server_default="0", default=0.0)
    budget_period_start = Column(DateTime, nullable=True)
    # Highest budget-usage threshold (percent) already announced to this user
    # in the current period. 0 = nothing announced. Kept in step with the live
    # percentage in both directions, so a plan increase or an admin reset lets
    # the same warning fire again instead of being silently swallowed.
    budget_notice_level = Column(Integer, nullable=False, server_default="0", default=0)

    # Local-account TOTP (2FA). Secret is Fernet-encrypted at rest.
    totp_secret_encrypted = Column(Text, nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    # JSON list of SHA-256 hex digests of one-time backup codes
    totp_backup_codes_hashed = Column(JsonDocument, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    # Set when the account was permanently deleted. The row survives on purpose:
    # four audit tables reference ``users.id`` with ``ON DELETE SET NULL`` and
    # carry a ``BEFORE UPDATE`` append-only trigger, so PostgreSQL refuses the
    # DELETE outright - and the governance hash chain is computed over
    # ``actor_user_id``, so nulling it would make every event by that actor read
    # as tampered. Everything identifying is cleared instead; what remains is an
    # opaque id that keeps the audit trail verifiable.
    purged_at = Column(DateTime, nullable=True, index=True)

    groups = relationship("UserGroup", secondary=user_group_members, back_populates="members")
    role_assignments = relationship(
        "UserRoleAssignment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    logs = relationship("RequestLog", back_populates="user")
    user_api_keys = relationship("UserApiKey", back_populates="user")
    plan_assignments = relationship("PlanAssignment", back_populates="user", foreign_keys="PlanAssignment.user_id")
