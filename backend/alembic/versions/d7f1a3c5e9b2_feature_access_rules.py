"""Feature Access: turn the web Chat or Projects off for a user, a group or a department.

Revision ID: d7f1a3c5e9b2
Revises: c5e7a9b1d3f2
Create Date: 2026-10-04

Both sections were open to every active account, with no way to keep one
team out of Projects or to give a group the projects without the personal
chat. One table of rules, one per feature and subject: ``deny`` for a user,
a group or a department, and ``allow`` only for a user (to give a section
back to one person inside a denied group). With no rows nothing changes for
anybody, so this upgrade is invisible until an administrator adds a rule.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f1a3c5e9b2"
down_revision: str | None = "c5e7a9b1d3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "feature_access_rules"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("effect", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("feature IN ('chat', 'projects')", name="chk_feature_access_feature"),
        sa.CheckConstraint("effect IN ('allow', 'deny')", name="chk_feature_access_effect"),
        sa.CheckConstraint(
            "("
            "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN department IS NOT NULL THEN 1 ELSE 0 END)"
            ") = 1",
            name="chk_feature_access_one_target",
        ),
        sa.CheckConstraint("effect = 'deny' OR user_id IS NOT NULL", name="chk_feature_access_allow_user_only"),
        sa.UniqueConstraint("feature", "user_id", name="uq_feature_access_user"),
        sa.UniqueConstraint("feature", "group_id", name="uq_feature_access_group"),
        sa.UniqueConstraint("feature", "department", name="uq_feature_access_department"),
    )
    op.create_index("ix_feature_access_rules_feature", _TABLE, ["feature"])
    op.create_index("ix_feature_access_rules_user_id", _TABLE, ["user_id"])
    op.create_index("ix_feature_access_rules_group_id", _TABLE, ["group_id"])


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
