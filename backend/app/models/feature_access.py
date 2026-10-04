"""Who may use the web Chat, Projects and personal API keys: the Feature Access rules.

All three are open to everyone by default. An administrator turns one
off for a user, a group or a department with a ``deny`` rule, and can give
it back to one person inside a denied group or department with an ``allow``
rule on that person. That is the whole model, so the table is small:

- one rule per feature and subject (changing a rule changes its effect);
- ``allow`` exists only for a user - a group or department allow could
  never change a decision, since the default is open and a deny among
  groups and departments wins;
- the decision itself is :func:`app.services.feature_access_service.decide`.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.database import Base

#: The sections a rule can govern. A new one is a value here and in the check below.
FEATURE_CHAT = "chat"
FEATURE_PROJECTS = "projects"
#: The person's own API keys (Settings): making one, and every use of one at the gateway.
FEATURE_API_KEYS = "api_keys"
FEATURES: tuple[str, ...] = (FEATURE_CHAT, FEATURE_PROJECTS, FEATURE_API_KEYS)


class FeatureAccessRule(Base):
    """Deny (or, for one person, allow) one section of the web app."""

    __tablename__ = "feature_access_rules"
    __table_args__ = (
        CheckConstraint("feature IN ('chat', 'projects', 'api_keys')", name="chk_feature_access_feature"),
        CheckConstraint("effect IN ('allow', 'deny')", name="chk_feature_access_effect"),
        CheckConstraint(
            "("
            "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN department IS NOT NULL THEN 1 ELSE 0 END)"
            ") = 1",
            name="chk_feature_access_one_target",
        ),
        CheckConstraint(
            "effect = 'deny' OR user_id IS NOT NULL",
            name="chk_feature_access_allow_user_only",
        ),
        UniqueConstraint("feature", "user_id", name="uq_feature_access_user"),
        UniqueConstraint("feature", "group_id", name="uq_feature_access_group"),
        UniqueConstraint("feature", "department", name="uq_feature_access_department"),
    )

    id = Column(Integer, primary_key=True)
    feature = Column(String(32), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(Integer, ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    #: As the administrator typed it; matched to ``User.department`` case- and space-insensitively.
    department = Column(String(255), nullable=True)
    effect = Column(String(8), nullable=False, default="deny")
    note = Column(String(500), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
