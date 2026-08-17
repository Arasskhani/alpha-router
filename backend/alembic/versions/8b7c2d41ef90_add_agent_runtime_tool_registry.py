"""add agent runtime tool registry

Revision ID: 8b7c2d41ef90
Revises: 31adeeec2bce
Create Date: 2026-08-12 14:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8b7c2d41ef90"
down_revision: str | None = "31adeeec2bce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonDocument = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "agent_tools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="chk_agent_tools_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_tools", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_agent_tools_created_by_user_id"),
            ["created_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tools_slug"),
            ["slug"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tools_status"),
            ["status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_agent_tools_status_name",
            ["status", "name"],
            unique=False,
        )

    op.create_table(
        "agent_tool_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_schema", JsonDocument, nullable=False),
        sa.Column("output_schema", JsonDocument, nullable=False),
        sa.Column("handler_key", sa.String(length=128), nullable=False),
        sa.Column("effect_type", sa.String(length=24), nullable=False),
        sa.Column("required_permission", sa.String(length=128), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("idempotent", sa.Boolean(), nullable=False),
        sa.Column("approval_mode", sa.String(length=16), nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=True),
        sa.Column("model_compatibility", JsonDocument, nullable=False),
        sa.Column("rate_limit_policy", JsonDocument, nullable=False),
        sa.Column("cost_policy", JsonDocument, nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("active_scope_key", sa.String(length=80), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("last_modified_by_user_id", sa.Integer(), nullable=True),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("published_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "approval_mode IN ('never', 'required')",
            name="chk_agent_tool_versions_approval",
        ),
        sa.CheckConstraint(
            "effect_type IN ('read_only', 'side_effecting')",
            name="chk_agent_tool_versions_effect",
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 3",
            name="chk_agent_tool_versions_retries",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="chk_agent_tool_versions_status",
        ),
        sa.CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 120",
            name="chk_agent_tool_versions_timeout",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_modified_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"],
            ["agent_tools.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fingerprint",
            name="uq_agent_tool_versions_fingerprint",
        ),
        sa.UniqueConstraint(
            "tool_id",
            "version_number",
            name="uq_agent_tool_versions_number",
        ),
    )
    with op.batch_alter_table("agent_tool_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_active_scope_key"),
            ["active_scope_key"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_created_by_user_id"),
            ["created_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_effect_type"),
            ["effect_type"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_last_modified_by_user_id"),
            ["last_modified_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_published_at"),
            ["published_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_published_by_user_id"),
            ["published_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_status"),
            ["status"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_submitted_by_user_id"),
            ["submitted_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_versions_tool_id"),
            ["tool_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_agent_tool_versions_tool_status",
            ["tool_id", "status", "version_number"],
            unique=False,
        )

    op.create_table(
        "agent_tool_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=36), nullable=True),
        sa.Column("tool_version_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", JsonDocument, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"],
            ["agent_tools.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_version_id"],
            ["agent_tool_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agent_tool_audit_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_agent_tool_audit_events_actor_user_id"),
            ["actor_user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_audit_events_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_audit_events_event_type"),
            ["event_type"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_audit_events_tool_id"),
            ["tool_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_agent_tool_audit_events_tool_version_id"),
            ["tool_version_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_agent_tool_audit_actor_time",
            ["actor_user_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_agent_tool_audit_tool_time",
            ["tool_id", "created_at"],
            unique=False,
        )

    with op.batch_alter_table("agent_handoff_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("turn_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("turn_ordinal", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("decided_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("failure_code", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("context_digest", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "context_payload",
                JsonDocument,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.create_foreign_key(
            "fk_agent_handoff_decided_by_user",
            "users",
            ["decided_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        sa.text("UPDATE agent_handoff_events SET turn_id = id WHERE turn_id IS NULL")
    )
    op.execute(
        sa.text(
            "UPDATE agent_handoff_events "
            "SET turn_ordinal = 1 "
            "WHERE turn_ordinal IS NULL"
        )
    )
    with op.batch_alter_table("agent_handoff_events", schema=None) as batch_op:
        batch_op.alter_column(
            "turn_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.alter_column(
            "turn_ordinal",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "context_payload",
            existing_type=JsonDocument,
            server_default=None,
        )
        batch_op.create_check_constraint(
            "chk_agent_handoff_turn_ordinal",
            "turn_ordinal BETWEEN 1 AND 4",
        )
        batch_op.create_unique_constraint(
            "uq_agent_handoff_turn_ordinal",
            ["session_id", "turn_id", "turn_ordinal"],
        )
        batch_op.create_index(
            batch_op.f("ix_agent_handoff_events_turn_id"),
            ["turn_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_agent_handoff_session_turn",
            ["session_id", "turn_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_handoff_events", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_handoff_session_turn")
        batch_op.drop_index(batch_op.f("ix_agent_handoff_events_turn_id"))
        batch_op.drop_constraint(
            "uq_agent_handoff_turn_ordinal",
            type_="unique",
        )
        batch_op.drop_constraint(
            "chk_agent_handoff_turn_ordinal",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_agent_handoff_decided_by_user",
            type_="foreignkey",
        )
        batch_op.drop_column("context_payload")
        batch_op.drop_column("context_digest")
        batch_op.drop_column("failure_code")
        batch_op.drop_column("decided_by_user_id")
        batch_op.drop_column("turn_ordinal")
        batch_op.drop_column("turn_id")

    with op.batch_alter_table("agent_tool_audit_events", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_tool_audit_tool_time")
        batch_op.drop_index("ix_agent_tool_audit_actor_time")
        batch_op.drop_index(batch_op.f("ix_agent_tool_audit_events_tool_version_id"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_audit_events_tool_id"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_audit_events_event_type"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_audit_events_created_at"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_audit_events_actor_user_id"))
    op.drop_table("agent_tool_audit_events")

    with op.batch_alter_table("agent_tool_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_tool_versions_tool_status")
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_tool_id"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_submitted_by_user_id"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_status"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_published_by_user_id"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_published_at"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_effect_type"))
        batch_op.drop_index(
            batch_op.f("ix_agent_tool_versions_last_modified_by_user_id")
        )
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_created_by_user_id"))
        batch_op.drop_index(batch_op.f("ix_agent_tool_versions_active_scope_key"))
    op.drop_table("agent_tool_versions")

    with op.batch_alter_table("agent_tools", schema=None) as batch_op:
        batch_op.drop_index("ix_agent_tools_status_name")
        batch_op.drop_index(batch_op.f("ix_agent_tools_status"))
        batch_op.drop_index(batch_op.f("ix_agent_tools_slug"))
        batch_op.drop_index(batch_op.f("ix_agent_tools_created_by_user_id"))
    op.drop_table("agent_tools")
