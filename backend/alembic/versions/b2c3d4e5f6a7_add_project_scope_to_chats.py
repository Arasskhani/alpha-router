"""add project scope to chat sessions and messages

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-19 11:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _existing_fks(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {fk["name"] for fk in inspector.get_foreign_keys(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # --- chat_sessions: add project scope columns ---
    session_columns = _existing_columns("chat_sessions")
    session_indexes = _existing_indexes("chat_sessions")
    session_fks = _existing_fks("chat_sessions")

    need_project_col = "project_id" not in session_columns
    need_project_fk = "fk_chat_sessions_project_id" not in session_fks
    need_created_col = "created_by_user_id" not in session_columns
    need_created_fk = "fk_chat_sessions_created_by_user_id" not in session_fks

    if is_sqlite and (need_project_col or need_project_fk or need_created_col or need_created_fk):
        # SQLite: use batch_alter_table for column + FK additions.
        with op.batch_alter_table("chat_sessions") as batch_op:
            if need_project_col:
                batch_op.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
            if need_project_fk:
                batch_op.create_foreign_key(
                    "fk_chat_sessions_project_id",
                    "projects",
                    ["project_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if need_created_col:
                batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
            if need_created_fk:
                batch_op.create_foreign_key(
                    "fk_chat_sessions_created_by_user_id",
                    "users",
                    ["created_by_user_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
    else:
        # PostgreSQL: direct ALTER TABLE.
        if need_project_col:
            op.add_column("chat_sessions", sa.Column("project_id", sa.String(length=36), nullable=True))
        if need_project_fk:
            op.create_foreign_key(
                "fk_chat_sessions_project_id",
                "chat_sessions",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if need_created_col:
            op.add_column("chat_sessions", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        if need_created_fk:
            op.create_foreign_key(
                "fk_chat_sessions_created_by_user_id",
                "chat_sessions",
                "users",
                ["created_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # Refresh index list after batch alter (table was recreated).
    session_indexes = _existing_indexes("chat_sessions")
    if "ix_chat_sessions_project_id" not in session_indexes:
        op.create_index("ix_chat_sessions_project_id", "chat_sessions", ["project_id"])
    if "ix_chat_sessions_created_by_user_id" not in session_indexes:
        op.create_index("ix_chat_sessions_created_by_user_id", "chat_sessions", ["created_by_user_id"])
    if "ix_chat_sessions_project_updated" not in session_indexes:
        op.create_index("ix_chat_sessions_project_updated", "chat_sessions", ["project_id", "updated_at"])

    # --- chat_messages: make user_id nullable, add author_display_name ---
    msg_columns = _existing_columns("chat_messages")
    if "author_display_name" not in msg_columns:
        op.add_column(
            "chat_messages",
            sa.Column("author_display_name", sa.String(length=255), nullable=True),
        )

    with op.batch_alter_table(
        "chat_messages",
        reflect_kwargs={"resolve_fks": False},
    ) as batch_op:
        batch_op.alter_column("user_id", nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    with op.batch_alter_table(
        "chat_messages",
        reflect_kwargs={"resolve_fks": False},
    ) as batch_op:
        batch_op.alter_column("user_id", nullable=False)

    op.drop_column("chat_messages", "author_display_name")

    op.drop_index("ix_chat_sessions_project_updated", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_created_by_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_project_id", table_name="chat_sessions")

    if is_sqlite:
        with op.batch_alter_table("chat_sessions") as batch_op:
            batch_op.drop_constraint("fk_chat_sessions_created_by_user_id", type_="foreignkey")
            batch_op.drop_column("created_by_user_id")
            batch_op.drop_constraint("fk_chat_sessions_project_id", type_="foreignkey")
            batch_op.drop_column("project_id")
    else:
        op.drop_constraint("fk_chat_sessions_created_by_user_id", "chat_sessions", type_="foreignkey")
        op.drop_column("chat_sessions", "created_by_user_id")
        op.drop_constraint("fk_chat_sessions_project_id", "chat_sessions", type_="foreignkey")
        op.drop_column("chat_sessions", "project_id")
