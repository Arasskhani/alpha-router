"""add automatic project memory tables and columns

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-25 13:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def _column_names(inspector, table: str) -> set[str]:
    if not _table_exists(inspector, table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _index_exists(inspector, table: str, index: str) -> bool:
    if not _table_exists(inspector, table):
        return False
    return index in {
        idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")
    }


def _add_column_if_missing(inspector, table: str, column: sa.Column) -> None:
    if column.name in _column_names(inspector, table):
        return
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(column)
    else:
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    memory_columns = [
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column(
            "sensitivity", sa.String(length=16), nullable=False, server_default="normal"
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("salience", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_session_id", sa.String(length=36), nullable=True),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column(
            "embedding_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_dims", sa.Integer(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    ]
    if _table_exists(inspector, "project_memories"):
        for column in memory_columns:
            _add_column_if_missing(inspector, "project_memories", column)
            inspector = sa.inspect(bind)

        # Pre-existing rows are owner-authored; keep them authoritative and
        # exempt from the auto pipeline's embedding backlog until first use.
        op.execute(
            sa.text(
                "UPDATE project_memories SET source_type = 'manual' "
                "WHERE source_type IS NULL OR source_type = ''"
            )
        )

        for index_name, columns in (
            (
                "ix_project_memories_project_enabled_salience",
                ["project_id", "enabled", "salience"],
            ),
            ("ix_project_memories_embedding_status", ["embedding_status"]),
            ("ix_project_memories_expires_at", ["expires_at"]),
            ("ix_project_memories_deleted_at", ["deleted_at"]),
        ):
            if not _index_exists(inspector, "project_memories", index_name):
                op.create_index(index_name, "project_memories", columns)
                inspector = sa.inspect(bind)

        existing_fks = {
            fk.get("name")
            for fk in inspector.get_foreign_keys("project_memories")
            if fk.get("name")
        }
        if not is_sqlite:
            for name, referent, local_cols in (
                ("fk_project_memories_source_session_id", "chat_sessions", ["source_session_id"]),
                ("fk_project_memories_source_message_id", "chat_messages", ["source_message_id"]),
                ("fk_project_memories_supersedes_id", "project_memories", ["supersedes_id"]),
            ):
                if name in existing_fks:
                    continue
                op.create_foreign_key(
                    name,
                    "project_memories",
                    referent,
                    local_cols,
                    ["id"],
                    ondelete="SET NULL",
                )

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_config_versions"):
        _add_column_if_missing(
            inspector,
            "project_config_versions",
            sa.Column(
                "memory_auto_capture",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_memory_jobs"):
        op.create_table(
            "project_memory_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("watermark_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("extracted_sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("run_after", sa.DateTime(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("worker_id", sa.String(length=64), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
            ),
        )
        op.create_index(
            "ix_project_memory_jobs_project_id", "project_memory_jobs", ["project_id"]
        )
        op.create_index(
            "ix_project_memory_jobs_session_id", "project_memory_jobs", ["session_id"]
        )
        op.create_index(
            "ix_project_memory_jobs_run_after", "project_memory_jobs", ["run_after"]
        )
        op.create_index(
            "ix_project_memory_jobs_status_run",
            "project_memory_jobs",
            ["status", "run_after"],
        )
        op.create_index(
            "ux_project_memory_jobs_open",
            "project_memory_jobs",
            ["project_id", "session_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('pending', 'retry')"),
            postgresql_where=sa.text("status IN ('pending', 'retry')"),
        )

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_memory_events"):
        op.create_table(
            "project_memory_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("memory_id", sa.String(length=36), nullable=True),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("actor", sa.String(length=16), nullable=False, server_default="system"),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["memory_id"], ["project_memories.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_project_memory_events_project_id", "project_memory_events", ["project_id"]
        )
        op.create_index(
            "ix_project_memory_events_memory_id", "project_memory_events", ["memory_id"]
        )
        op.create_index(
            "ix_project_memory_events_created", "project_memory_events", ["created_at"]
        )

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_memory_suppressions"):
        op.create_table(
            "project_memory_suppressions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "vector_indexed", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "project_id",
                "content_hash",
                name="ux_project_memory_suppressions_project_hash",
            ),
        )
        op.create_index(
            "ix_project_memory_suppressions_project_id",
            "project_memory_suppressions",
            ["project_id"],
        )
        op.create_index(
            "ix_project_memory_suppressions_content_hash",
            "project_memory_suppressions",
            ["content_hash"],
        )
        op.create_index(
            "ix_project_memory_suppressions_expires",
            "project_memory_suppressions",
            ["expires_at"],
        )

    if not is_sqlite:
        try:
            op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            op.execute(
                sa.text(
                    "CREATE INDEX IF NOT EXISTS ix_project_memories_content_trgm "
                    "ON project_memories USING gin (lower(content) gin_trgm_ops)"
                )
            )
        except Exception:
            # CREATE EXTENSION may lack privileges; lexical search falls back to ILIKE.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_memory_suppressions"):
        op.drop_table("project_memory_suppressions")
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_memory_events"):
        op.drop_table("project_memory_events")
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_memory_jobs"):
        op.drop_table("project_memory_jobs")
