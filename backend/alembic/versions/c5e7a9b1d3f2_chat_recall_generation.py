"""A generation per chat's recall index, so its vectors are deleted after a forget commits, and retried.

Revision ID: c5e7a9b1d3f2
Revises: a4c6e8f0b2d1
Create Date: 2026-09-30

A rewrite, a purge or a delete-all took the chat's vectors out of the store
in the request, before its transaction committed, once: with the store down
they stayed (the database check kept their words out of recall), and a
transaction that then rolled back had lost vectors it still needed. The
deletion is now queued with the forget, run after it commits and retried;
each forget raises the chat's generation, each point carries the one it was
written under, and the deletion takes only points written before it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5e7a9b1d3f2"
down_revision: str | None = "a4c6e8f0b2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_recall_index"
_COLUMN = "generation"


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    if _COLUMN not in _columns():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    if _COLUMN in _columns():
        op.drop_column(_TABLE, _COLUMN)
