"""User accounts, RBAC, and directory profile fields."""

import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base

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
    # local | ldap | keycloak
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

    role = Column(String(64), default="user")  # RBAC role slug
    auth_provider = Column(String(32), default="local")  # local | ldap | keycloak
    external_id = Column(String(255), nullable=True, index=True)
    is_active = Column(Boolean, default=True)

    # Directory / HR fields for reporting filters
    job_title = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True, index=True)
    office = Column(String(255), nullable=True)
    reporting_to = Column(String(255), nullable=True)

    # Budget: resolved from plan assignment; cached monthly remaining
    monthly_budget_usd = Column(Float, default=0.0)
    budget_used_usd = Column(Float, default=0.0)
    budget_period_start = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

    groups = relationship("UserGroup", secondary=user_group_members, back_populates="members")
    role_assignments = relationship(
        "UserRoleAssignment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    logs = relationship("RequestLog", back_populates="user")
    user_api_keys = relationship("UserApiKey", back_populates="user")
    plan_assignments = relationship("PlanAssignment", back_populates="user", foreign_keys="PlanAssignment.user_id")
