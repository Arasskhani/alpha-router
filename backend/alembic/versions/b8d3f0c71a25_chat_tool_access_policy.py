"""Who may use which chat tool.

Revision ID: b8d3f0c71a25
Revises: c7e2a9f14b60
Create Date: 2026-09-20

Every user who could reach a model could use every tool in the chat composer:
web search, image and video generation, the sandbox that runs Python. There
was no way to give Code Interpreter to the data team and not to everyone, and
no record of such a decision if one had been made.

Two tables, shaped like every other ACL in this product - an access type per
resource, and one allow/deny row per principal, exactly one target each. The
resource here is a tool key from the registry in
``app.services.chat_tool_registry`` rather than a row in another table, which
is deliberate: registering a new tool must not require a migration. A tool
with no policy row is governed by the default in its registry entry, which is
``public``, so this upgrade changes nothing for anybody until an administrator
restricts something.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d3f0c71a25"
down_revision: str | None = "c7e2a9f14b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICIES = "chat_tool_policies"
_ASSIGNMENTS = "chat_tool_access_assignments"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if _POLICIES not in tables:
        op.create_table(
            _POLICIES,
            sa.Column("tool_key", sa.String(length=64), primary_key=True),
            sa.Column("access_type", sa.String(length=16), nullable=False),
            sa.Column("acl_version", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column(
                "updated_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.CheckConstraint(
                "access_type IN ('public', 'private')",
                name="chk_chat_tool_policies_access_type",
            ),
        )

    if _ASSIGNMENTS not in tables:
        op.create_table(
            _ASSIGNMENTS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tool_key", sa.String(length=64), nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "group_id",
                sa.Integer(),
                sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("department", sa.String(length=255), nullable=True),
            sa.Column("role_slug", sa.String(length=64), nullable=True),
            sa.Column("effect", sa.String(length=8), nullable=False),
            sa.Column(
                "assigned_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("assigned_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "("
                "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) + "
                "(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) + "
                "(CASE WHEN department IS NOT NULL THEN 1 ELSE 0 END) + "
                "(CASE WHEN role_slug IS NOT NULL THEN 1 ELSE 0 END)"
                ") = 1",
                name="chk_chat_tool_access_one_target",
            ),
            sa.CheckConstraint(
                "effect IN ('allow', 'deny')",
                name="chk_chat_tool_access_effect",
            ),
            sa.UniqueConstraint("tool_key", "user_id", "effect", name="uq_chat_tool_access_user_effect"),
            sa.UniqueConstraint("tool_key", "group_id", "effect", name="uq_chat_tool_access_group_effect"),
            sa.UniqueConstraint(
                "tool_key", "department", "effect", name="uq_chat_tool_access_department_effect"
            ),
            sa.UniqueConstraint("tool_key", "role_slug", "effect", name="uq_chat_tool_access_role_effect"),
        )
        op.create_index("ix_chat_tool_access_assignments_tool_key", _ASSIGNMENTS, ["tool_key"])
        op.create_index("ix_chat_tool_access_assignments_user_id", _ASSIGNMENTS, ["user_id"])
        op.create_index("ix_chat_tool_access_assignments_group_id", _ASSIGNMENTS, ["group_id"])
        op.create_index("ix_chat_tool_access_assignments_department", _ASSIGNMENTS, ["department"])
        op.create_index("ix_chat_tool_access_assignments_role_slug", _ASSIGNMENTS, ["role_slug"])
        op.create_index("ix_chat_tool_access_assignments_effect", _ASSIGNMENTS, ["effect"])
        op.create_index("ix_chat_tool_access_key_effect", _ASSIGNMENTS, ["tool_key", "effect"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _ASSIGNMENTS in tables:
        op.drop_table(_ASSIGNMENTS)
    if _POLICIES in tables:
        op.drop_table(_POLICIES)
