"""Who may use which chat tool.

The other access-controlled things in this product - agents, knowledge bases,
documents, catalog models - are rows, so their ``access_type`` and ACL version
live on the row itself. A chat tool is not a row: it is code, declared in
:mod:`app.services.chat_tool_registry`. These two tables give it the same
shape anyway, keyed by the registry's ``tool_key``.

Keyed by a string rather than a foreign key on purpose. Registering a tool
adds an entry to the registry, not a column here and not a migration: the
policy row is created the first time an administrator saves one, and a tool
with no row is governed by the default in its registry entry. That is what
lets a tool ship with access control already working.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.database import Base
from app.models.knowledge import one_acl_target_constraint


class ChatToolPolicy(Base):
    """The access type of one registered chat tool.

    ``acl_version`` exists for the same reason it does on an agent: something
    that caches an access decision needs to know when the answer changed.
    """

    __tablename__ = "chat_tool_policies"
    __table_args__ = (
        CheckConstraint(
            "access_type IN ('public', 'private')",
            name="chk_chat_tool_policies_access_type",
        ),
    )

    #: A key from the registry. Not a foreign key - the tools are code.
    tool_key = Column(String(64), primary_key=True)
    access_type = Column(String(16), nullable=False, default="public")
    acl_version = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )
    updated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ChatToolAccessAssignment(Base):
    """Allow or deny one principal the use of one chat tool.

    Exactly one target per row, and ``deny`` wins over ``allow`` - the same
    rules :mod:`app.services.resource_access_service` applies everywhere else,
    evaluated by the same code.
    """

    __tablename__ = "chat_tool_access_assignments"
    __table_args__ = (
        one_acl_target_constraint("chk_chat_tool_access_one_target"),
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="chk_chat_tool_access_effect",
        ),
        UniqueConstraint("tool_key", "user_id", "effect", name="uq_chat_tool_access_user_effect"),
        UniqueConstraint("tool_key", "group_id", "effect", name="uq_chat_tool_access_group_effect"),
        UniqueConstraint("tool_key", "department", "effect", name="uq_chat_tool_access_department_effect"),
        UniqueConstraint("tool_key", "role_slug", "effect", name="uq_chat_tool_access_role_effect"),
        Index("ix_chat_tool_access_key_effect", "tool_key", "effect"),
    )

    id = Column(Integer, primary_key=True)
    tool_key = Column(String(64), nullable=False, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    group_id = Column(
        Integer,
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    department = Column(String(255), nullable=True, index=True)
    role_slug = Column(String(64), nullable=True, index=True)
    effect = Column(String(8), nullable=False, default="allow", index=True)
    assigned_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
