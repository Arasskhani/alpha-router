"""add chat session channel_kind and project room handoffs

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-22 19:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
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
    return index in {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def _constraint_exists(inspector, table: str, name: str) -> bool:
    if not _table_exists(inspector, table):
        return False
    checks = inspector.get_check_constraints(table) if hasattr(inspector, "get_check_constraints") else []
    return name in {item.get("name") for item in checks if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    session_columns = _column_names(inspector, "chat_sessions")
    if "channel_kind" not in session_columns:
        if is_sqlite:
            with op.batch_alter_table("chat_sessions") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "channel_kind",
                        sa.String(length=16),
                        nullable=False,
                        server_default="ai",
                    )
                )
                batch_op.create_check_constraint(
                    "chk_chat_sessions_channel_kind",
                    "channel_kind IN ('ai', 'member')",
                )
        else:
            op.add_column(
                "chat_sessions",
                sa.Column(
                    "channel_kind",
                    sa.String(length=16),
                    nullable=False,
                    server_default="ai",
                ),
            )
            op.create_check_constraint(
                "chk_chat_sessions_channel_kind",
                "chat_sessions",
                "channel_kind IN ('ai', 'member')",
            )
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "chat_sessions"):
        op.execute(sa.text("UPDATE chat_sessions SET channel_kind = 'ai' WHERE channel_kind IS NULL"))
        if not _index_exists(inspector, "chat_sessions", "ix_chat_sessions_project_channel_updated"):
            op.create_index(
                "ix_chat_sessions_project_channel_updated",
                "chat_sessions",
                ["project_id", "channel_kind", "updated_at"],
            )

    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_room_handoffs"):
        op.create_table(
            "project_room_handoffs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("source_session_id", sa.String(length=36), nullable=False),
            sa.Column("target_session_id", sa.String(length=36), nullable=False),
            sa.Column("brief", sa.Text(), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["source_session_id"],
                ["chat_sessions.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["target_session_id"],
                ["chat_sessions.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "ix_project_room_handoffs_source",
            "project_room_handoffs",
            ["source_session_id"],
        )
        op.create_index(
            "ix_project_room_handoffs_target",
            "project_room_handoffs",
            ["target_session_id"],
        )
        op.create_index(
            "ix_project_room_handoffs_created",
            "project_room_handoffs",
            ["created_at"],
        )
        op.create_index(
            "ix_project_room_handoffs_created_by_user_id",
            "project_room_handoffs",
            ["created_by_user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_room_handoffs"):
        op.drop_table("project_room_handoffs")
        inspector = sa.inspect(bind)

    if _index_exists(inspector, "chat_sessions", "ix_chat_sessions_project_channel_updated"):
        op.drop_index("ix_chat_sessions_project_channel_updated", table_name="chat_sessions")

    if "channel_kind" in _column_names(inspector, "chat_sessions"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("chat_sessions") as batch_op:
                if _constraint_exists(inspector, "chat_sessions", "chk_chat_sessions_channel_kind"):
                    batch_op.drop_constraint("chk_chat_sessions_channel_kind", type_="check")
                batch_op.drop_column("channel_kind")
        else:
            if _constraint_exists(inspector, "chat_sessions", "chk_chat_sessions_channel_kind"):
                op.drop_constraint("chk_chat_sessions_channel_kind", "chat_sessions", type_="check")
            op.drop_column("chat_sessions", "channel_kind")
