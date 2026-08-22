"""add per-user project chat composer prefs (tools, model, Agent)

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-08-19 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonDocument = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=Text()),
    "postgresql",
)


def _table_exists(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def _index_exists(inspector, table: str, index: str) -> bool:
    return index in {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "project_chat_composer_prefs"):
        op.create_table(
            "project_chat_composer_prefs",
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("tools", JsonDocument, nullable=False),
            sa.Column("tools_touched", sa.Boolean(), nullable=False),
            sa.Column("model_id", sa.String(length=512), nullable=True),
            sa.Column("selected_agent_slug", sa.String(length=128), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("project_id", "session_id", "user_id"),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["projects.id"],
                name="fk_project_chat_composer_prefs_project_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["chat_sessions.id"],
                name="fk_project_chat_composer_prefs_session_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_project_chat_composer_prefs_user_id",
                ondelete="CASCADE",
            ),
        )
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "project_chat_composer_prefs"):
        if not _index_exists(
            inspector, "project_chat_composer_prefs", "ix_project_chat_composer_prefs_user"
        ):
            op.create_index(
                "ix_project_chat_composer_prefs_user",
                "project_chat_composer_prefs",
                ["user_id"],
            )
        if not _index_exists(
            inspector,
            "project_chat_composer_prefs",
            "ix_project_chat_composer_prefs_session",
        ):
            op.create_index(
                "ix_project_chat_composer_prefs_session",
                "project_chat_composer_prefs",
                ["session_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_chat_composer_prefs"):
        return
    for index_name in (
        "ix_project_chat_composer_prefs_session",
        "ix_project_chat_composer_prefs_user",
    ):
        if _index_exists(inspector, "project_chat_composer_prefs", index_name):
            op.drop_index(index_name, table_name="project_chat_composer_prefs")
    op.drop_table("project_chat_composer_prefs")
