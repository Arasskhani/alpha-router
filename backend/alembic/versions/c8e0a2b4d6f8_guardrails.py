"""Guardrails: patterns, rules, who they apply to, what they did; how far each connection is trusted.

Revision ID: c8e0a2b4d6f8
Revises: b7d9f1a3c5e7
Create Date: 2026-10-19

Every table starts empty: until an administrator writes a rule, Guardrails
does nothing. ``connections.trust_level`` starts as ``public`` for every
connection, the strictest level, until an administrator says otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8e0a2b4d6f8"
down_revision: str | None = "b7d9f1a3c5e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ONE_TARGET = (
    "("
    "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN department IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN role_slug IS NOT NULL THEN 1 ELSE 0 END)"
    ") = 1"
)


def upgrade() -> None:
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trust_level", sa.String(length=16), nullable=False, server_default="public"))
        batch_op.create_check_constraint("chk_connections_trust_level", "trust_level IN ('internal', 'trusted', 'public')")

    op.create_table(
        "guardrail_patterns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column("entries_json", sa.Text(), nullable=True),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("normalize", sa.Boolean(), nullable=False),
        sa.Column("context_words_json", sa.Text(), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("validator", sa.String(length=32), nullable=True),
        sa.Column("never_match_json", sa.Text(), nullable=True),
        sa.Column("redact_label", sa.String(length=32), nullable=False),
        sa.Column("must_match_json", sa.Text(), nullable=True),
        sa.Column("must_not_match_json", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('regex', 'words', 'domains')", name="chk_guardrail_patterns_kind"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "guardrail_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("patterns_json", sa.Text(), nullable=False),
        sa.Column("match_mode", sa.String(length=8), nullable=False),
        sa.Column("min_matches", sa.Integer(), nullable=False),
        sa.Column("channels_json", sa.Text(), nullable=False),
        sa.Column("destinations_json", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("route_model_id", sa.Integer(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=True),
        sa.Column("access_type", sa.String(length=16), nullable=False),
        sa.Column("acl_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("mode IN ('off', 'monitor', 'enforce')", name="chk_guardrail_rules_mode"),
        sa.CheckConstraint("action IN ('block', 'redact', 'route')", name="chk_guardrail_rules_action"),
        sa.CheckConstraint("match_mode IN ('any', 'all')", name="chk_guardrail_rules_match_mode"),
        sa.CheckConstraint("access_type IN ('public', 'private')", name="chk_guardrail_rules_access_type"),
        sa.ForeignKeyConstraint(["route_model_id"], ["ai_models.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guardrail_rules_position", "guardrail_rules", ["position"], unique=False)

    op.create_table(
        "guardrail_rule_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("role_slug", sa.String(length=64), nullable=True),
        sa.Column("effect", sa.String(length=8), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(_ONE_TARGET, name="chk_guardrail_rule_access_one_target"),
        sa.CheckConstraint("effect IN ('allow', 'deny')", name="chk_guardrail_rule_access_effect"),
        sa.ForeignKeyConstraint(["rule_id"], ["guardrail_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["user_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "user_id", "effect", name="uq_guardrail_rule_access_user_effect"),
        sa.UniqueConstraint("rule_id", "group_id", "effect", name="uq_guardrail_rule_access_group_effect"),
        sa.UniqueConstraint("rule_id", "department", "effect", name="uq_guardrail_rule_access_department_effect"),
        sa.UniqueConstraint("rule_id", "role_slug", "effect", name="uq_guardrail_rule_access_role_effect"),
    )
    op.create_index("ix_guardrail_rule_assignments_rule_id", "guardrail_rule_assignments", ["rule_id"], unique=False)
    op.create_index("ix_guardrail_rule_assignments_user_id", "guardrail_rule_assignments", ["user_id"], unique=False)
    op.create_index(
        "ix_guardrail_rule_assignments_group_id", "guardrail_rule_assignments", ["group_id"], unique=False
    )

    op.create_table(
        "guardrail_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("rule_name", sa.String(length=120), nullable=True),
        sa.Column("rule_version", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("intended_action", sa.String(length=16), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("destination", sa.String(length=160), nullable=True),
        sa.Column("destination_trust", sa.String(length=16), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("alpha_router_api_key_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("model_ref", sa.String(length=255), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["guardrail_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["alpha_router_api_key_id"], ["alpha_router_api_keys.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guardrail_events_created_at", "guardrail_events", ["created_at"], unique=False)
    op.create_index("ix_guardrail_events_user_id", "guardrail_events", ["user_id"], unique=False)
    op.create_index("ix_guardrail_events_action_created", "guardrail_events", ["action", "created_at"], unique=False)
    op.create_index("ix_guardrail_events_rule_created", "guardrail_events", ["rule_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_guardrail_events_rule_created", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_action_created", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_user_id", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_created_at", table_name="guardrail_events")
    op.drop_table("guardrail_events")
    op.drop_index("ix_guardrail_rule_assignments_group_id", table_name="guardrail_rule_assignments")
    op.drop_index("ix_guardrail_rule_assignments_user_id", table_name="guardrail_rule_assignments")
    op.drop_index("ix_guardrail_rule_assignments_rule_id", table_name="guardrail_rule_assignments")
    op.drop_table("guardrail_rule_assignments")
    op.drop_index("ix_guardrail_rules_position", table_name="guardrail_rules")
    op.drop_table("guardrail_rules")
    op.drop_table("guardrail_patterns")
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_constraint("chk_connections_trust_level", type_="check")
        batch_op.drop_column("trust_level")
