"""add projects domain

Revision ID: a1b2c3d4e5f6
Revises: d1a5f3c06e42
Create Date: 2026-08-19 11:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d1a5f3c06e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonDocument = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)


def upgrade() -> None:
    # Create project_config_versions first (without FK to projects, to avoid circular dependency).
    op.create_table(
        "project_config_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("custom_prompt", sa.Text(), nullable=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("grounding_policy", JsonDocument, nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_config_versions_project",
        "project_config_versions",
        ["project_id"],
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("active_config_version_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("acl_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'deletion_pending')",
            name="chk_projects_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')",
            name="chk_projects_visibility",
        ),
        sa.ForeignKeyConstraint(
            ["active_config_version_id"],
            ["project_config_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_status_updated", "projects", ["status", "updated_at"])
    op.create_index("ix_projects_visibility", "projects", ["visibility"])

    # Now add the deferred FK from project_config_versions to projects (breaks the cycle).
    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT, so use batch_alter_table.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("project_config_versions") as batch_op:
            batch_op.create_foreign_key(
                "fk_project_config_versions_project_id",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="CASCADE",
            )
    else:
        op.create_foreign_key(
            "fk_project_config_versions_project_id",
            "project_config_versions",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.create_table(
        "project_members",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'contributor', 'viewer')",
            name="chk_project_members_role",
        ),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_index(
        "ix_project_members_project_role",
        "project_members",
        ["project_id", "role"],
    )

    op.create_table(
        "project_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("claimed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('contributor', 'viewer')",
            name="chk_project_invitations_role",
        ),
        sa.ForeignKeyConstraint(["claimed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_invitations_project",
        "project_invitations",
        ["project_id"],
    )
    op.create_index(
        "ix_project_invitations_token_hash",
        "project_invitations",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "project_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_project_memories_project_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_memories_project_enabled",
        "project_memories",
        ["project_id", "enabled"],
    )

    op.create_table(
        "project_memory_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("consumer_project_id", sa.String(length=36), nullable=False),
        sa.Column("source_project_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "consumer_project_id <> source_project_id",
            name="chk_project_memory_grants_no_self",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="chk_project_memory_grants_status",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["consumer_project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "consumer_project_id",
            "source_project_id",
            name="uq_project_memory_grants_pair",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_memory_grants_consumer",
        "project_memory_grants",
        ["consumer_project_id"],
    )
    op.create_index(
        "ix_project_memory_grants_source",
        "project_memory_grants",
        ["source_project_id"],
    )

    op.create_table(
        "project_chat_pins",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("pinned_by_user_id", sa.Integer(), nullable=True),
        sa.Column("pinned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pinned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "project_id",
            "session_id",
            name="uq_project_chat_pins_session",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "project_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("payload_json", JsonDocument, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success', 'denied', 'failed')",
            name="chk_project_audit_outcome",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_audit_project_time",
        "project_audit_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_project_audit_actor_time",
        "project_audit_events",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_project_audit_event_type",
        "project_audit_events",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_audit_event_type", table_name="project_audit_events")
    op.drop_index("ix_project_audit_actor_time", table_name="project_audit_events")
    op.drop_index("ix_project_audit_project_time", table_name="project_audit_events")
    op.drop_table("project_audit_events")

    op.drop_table("project_chat_pins")

    op.drop_index("ix_project_memory_grants_source", table_name="project_memory_grants")
    op.drop_index("ix_project_memory_grants_consumer", table_name="project_memory_grants")
    op.drop_table("project_memory_grants")

    op.drop_index("ix_project_memories_project_enabled", table_name="project_memories")
    op.drop_table("project_memories")

    op.drop_index("ix_project_invitations_token_hash", table_name="project_invitations")
    op.drop_index("ix_project_invitations_project", table_name="project_invitations")
    op.drop_table("project_invitations")

    op.drop_index("ix_project_members_project_role", table_name="project_members")
    op.drop_table("project_members")

    # Drop the deferred FK before dropping projects.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("project_config_versions") as batch_op:
            batch_op.drop_constraint(
                "fk_project_config_versions_project_id",
                type_="foreignkey",
            )
    else:
        op.drop_constraint(
            "fk_project_config_versions_project_id",
            "project_config_versions",
            type_="foreignkey",
        )

    op.drop_index("ix_projects_visibility", table_name="projects")
    op.drop_index("ix_projects_status_updated", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_project_config_versions_project", table_name="project_config_versions")
    op.drop_table("project_config_versions")
