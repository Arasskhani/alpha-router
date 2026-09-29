"""What of each chat is indexed for recall in its owner's other chats.

Revision ID: c9e48be1dd4f
Revises: a2b0633f1fc9
Create Date: 2026-09-29

A new chat knew nothing of the person's earlier ones. Each chat's exchanges
(and a short digest of it) are now embedded into the memory collection in
Qdrant, so a new turn can find the earlier conversations it relates to. The
vectors carry ids only; this table records how far each chat is indexed,
what is never to be indexed (anything before the person's last delete-all),
and the indexing job's own state. One row per chat; it goes with the chat.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9e48be1dd4f"
down_revision: str | None = "a2b0633f1fc9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_recall_index"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("indexed_up_to", sa.Integer(), nullable=False),
        sa.Column("not_before", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("digest_hash", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_after", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_recall_index_user_id", _TABLE, ["user_id"])
    op.create_index("ix_chat_recall_index_project_id", _TABLE, ["project_id"])
    op.create_index("ix_chat_recall_index_status_run", _TABLE, ["status", "run_after"])


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_index("ix_chat_recall_index_status_run", table_name=_TABLE)
        op.drop_index("ix_chat_recall_index_project_id", table_name=_TABLE)
        op.drop_index("ix_chat_recall_index_user_id", table_name=_TABLE)
        op.drop_table(_TABLE)
