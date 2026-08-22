"""add per-user project prefs (last opened chat / recency)

Revision ID: a8b9c0d1e2f3
Revises: f6a7b8c9d0e1
Create Date: 2026-08-19 17:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def _index_exists(inspector, table: str, index: str) -> bool:
    return index in {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def _fk_exists(inspector, table: str, fk_name: str) -> bool:
    return fk_name in {
        fk["name"] for fk in inspector.get_foreign_keys(table) if fk.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "project_user_prefs"):
        op.create_table(
            "project_user_prefs",
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("last_opened_session_id", sa.String(length=36), nullable=True),
            sa.Column("last_opened_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("project_id", "user_id"),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name="fk_project_user_prefs_project_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_project_user_prefs_user_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["last_opened_session_id"],
                ["chat_sessions.id"],
                name="fk_project_user_prefs_last_opened_session_id",
                ondelete="SET NULL",
            ),
        )
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "project_user_prefs"):
        if not _index_exists(inspector, "project_user_prefs", "ix_project_user_prefs_user_opened"):
            op.create_index(
                "ix_project_user_prefs_user_opened",
                "project_user_prefs",
                ["user_id", "last_opened_at"],
            )
        if not _index_exists(
            inspector, "project_user_prefs", "ix_project_user_prefs_last_opened_session_id"
        ):
            op.create_index(
                "ix_project_user_prefs_last_opened_session_id",
                "project_user_prefs",
                ["last_opened_session_id"],
            )
        if not _index_exists(
            inspector, "project_user_prefs", "ix_project_user_prefs_last_opened_at"
        ):
            op.create_index(
                "ix_project_user_prefs_last_opened_at",
                "project_user_prefs",
                ["last_opened_at"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_user_prefs"):
        return
    for index_name in (
        "ix_project_user_prefs_last_opened_at",
        "ix_project_user_prefs_last_opened_session_id",
        "ix_project_user_prefs_user_opened",
    ):
        if _index_exists(inspector, "project_user_prefs", index_name):
            op.drop_index(index_name, table_name="project_user_prefs")
    for fk_name in (
        "fk_project_user_prefs_last_opened_session_id",
        "fk_project_user_prefs_user_id",
        "fk_project_user_prefs_project_id",
    ):
        if _fk_exists(inspector, "project_user_prefs", fk_name):
            op.drop_constraint(fk_name, "project_user_prefs", type_="foreignkey")
    op.drop_table("project_user_prefs")
