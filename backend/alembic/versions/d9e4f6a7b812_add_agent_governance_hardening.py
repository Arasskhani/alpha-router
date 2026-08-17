"""add agent governance hardening

Revision ID: d9e4f6a7b812
Revises: c4f1a92de673
Create Date: 2026-08-12 16:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d9e4f6a7b812"
down_revision: str | None = "c4f1a92de673"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonDocument = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)

_APPEND_ONLY_TABLES = (
    "agent_audit_events",
    "agent_tool_audit_events",
    "knowledge_audit_events",
    "governance_audit_events",
)


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION alpharouter_reject_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit table % is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table_name in _APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION alpharouter_reject_audit_mutation()
                """
            )
        return
    if dialect == "sqlite":
        for table_name in _APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'audit table is append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'audit table is append-only');
                END
                """
            )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in _APPEND_ONLY_TABLES:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"
            )
        op.execute("DROP FUNCTION IF EXISTS alpharouter_reject_audit_mutation()")
        return
    if dialect == "sqlite":
        for table_name in _APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_delete")


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "private_mode",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.create_index(
            "ix_agent_runs_private_mode",
            ["private_mode"],
            unique=False,
        )

    op.create_table(
        "governance_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("payload_json", JsonDocument, nullable=False),
        sa.Column("previous_event_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success', 'denied', 'failed', 'scheduled')",
            name="chk_governance_audit_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_hash",
            name="uq_governance_audit_events_event_hash",
        ),
    )
    op.create_index(
        "ix_governance_audit_events_event_type",
        "governance_audit_events",
        ["event_type"],
    )
    op.create_index(
        "ix_governance_audit_events_resource_type",
        "governance_audit_events",
        ["resource_type"],
    )
    op.create_index(
        "ix_governance_audit_events_resource_id",
        "governance_audit_events",
        ["resource_id"],
    )
    op.create_index(
        "ix_governance_audit_events_actor_user_id",
        "governance_audit_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_governance_audit_events_outcome",
        "governance_audit_events",
        ["outcome"],
    )
    op.create_index(
        "ix_governance_audit_events_event_hash",
        "governance_audit_events",
        ["event_hash"],
    )
    op.create_index(
        "ix_governance_audit_events_created_at",
        "governance_audit_events",
        ["created_at"],
    )
    op.create_index(
        "ix_governance_audit_resource_time",
        "governance_audit_events",
        ["resource_type", "resource_id", "created_at"],
    )
    op.create_index(
        "ix_governance_audit_actor_time",
        "governance_audit_events",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "uq_legal_holds_active_resource",
        "legal_holds",
        ["resource_type", "resource_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    _create_append_only_guards()


def downgrade() -> None:
    _drop_append_only_guards()
    op.drop_index("uq_legal_holds_active_resource", table_name="legal_holds")
    op.drop_index(
        "ix_governance_audit_actor_time",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_resource_time",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_created_at",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_event_hash",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_outcome",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_actor_user_id",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_resource_id",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_resource_type",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_events_event_type",
        table_name="governance_audit_events",
    )
    op.drop_table("governance_audit_events")
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_index("ix_agent_runs_private_mode")
        batch_op.drop_column("private_mode")
