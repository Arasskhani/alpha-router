"""add deferred FKs from chat tables to agent platform tables

These FKs were previously declared inline in the ORM models, which
caused ``create_all`` to fail on PostgreSQL because the referenced
agent-platform tables (agents, agent_versions, agent_runs) are
Alembic-owned and do not exist yet during legacy schema bootstrap.

The FKs are now added here, idempotently, after all agent-platform
tables have been created by earlier migrations.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-19 13:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk_exists(inspector, table: str, fk_name: str) -> bool:
    return fk_name in {
        fk["name"] for fk in inspector.get_foreign_keys(table) if fk.get("name")
    }


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    # --- chat_sessions.current_agent_id -> agents.id ---
    if _column_exists(inspector, "chat_sessions", "current_agent_id"):
        fk_name = "fk_chat_sessions_current_agent"
        if not _fk_exists(inspector, "chat_sessions", fk_name):
            if dialect == "sqlite":
                with op.batch_alter_table("chat_sessions") as batch_op:
                    batch_op.create_foreign_key(
                        fk_name, "agents",
                        ["current_agent_id"], ["id"],
                        ondelete="SET NULL",
                    )
            else:
                op.create_foreign_key(
                    fk_name, "chat_sessions", "agents",
                    ["current_agent_id"], ["id"],
                    ondelete="SET NULL",
                )

    # --- chat_sessions.current_agent_version_id -> agent_versions.id ---
    if _column_exists(inspector, "chat_sessions", "current_agent_version_id"):
        fk_name = "fk_chat_sessions_current_agent_version"
        if not _fk_exists(inspector, "chat_sessions", fk_name):
            if dialect == "sqlite":
                with op.batch_alter_table("chat_sessions") as batch_op:
                    batch_op.create_foreign_key(
                        fk_name, "agent_versions",
                        ["current_agent_version_id"], ["id"],
                        ondelete="SET NULL",
                    )
            else:
                op.create_foreign_key(
                    fk_name, "chat_sessions", "agent_versions",
                    ["current_agent_version_id"], ["id"],
                    ondelete="SET NULL",
                )

    # --- chat_messages.agent_run_id -> agent_runs.id ---
    if _column_exists(inspector, "chat_messages", "agent_run_id"):
        fk_name = "fk_chat_messages_agent_run"
        if not _fk_exists(inspector, "chat_messages", fk_name):
            if dialect == "sqlite":
                with op.batch_alter_table("chat_messages") as batch_op:
                    batch_op.create_foreign_key(
                        fk_name, "agent_runs",
                        ["agent_run_id"], ["id"],
                        ondelete="SET NULL",
                    )
            else:
                op.create_foreign_key(
                    fk_name, "chat_messages", "agent_runs",
                    ["agent_run_id"], ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    for table, fk_name in [
        ("chat_messages", "fk_chat_messages_agent_run"),
        ("chat_sessions", "fk_chat_sessions_current_agent_version"),
        ("chat_sessions", "fk_chat_sessions_current_agent"),
    ]:
        if _fk_exists(inspector, table, fk_name):
            if dialect == "sqlite":
                with op.batch_alter_table(table) as batch_op:
                    batch_op.drop_constraint(fk_name, type_="foreignkey")
            else:
                op.drop_constraint(fk_name, table, type_="foreignkey")
