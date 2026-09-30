"""A chat's digest for recall, written by the summary model.

Revision ID: a4c6e8f0b2d1
Revises: f1c8b2d4e6a9
Create Date: 2026-09-30

Each chat is found again in its owner's other chats by its exchanges and by
a digest of what it is about. For a chat without a summary - most chats -
the digest was its title and its first questions, which say little of what
it came to. The summary model now writes a few sentences on it, kept here
with how far the chat was read and under which delete-all it was written.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c6e8f0b2d1"
down_revision: str | None = "f1c8b2d4e6a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chat_recall_index"
_COLUMNS = (
    ("digest_text", sa.Text()),
    ("digest_up_to", sa.Integer()),
    ("digest_after", sa.Integer()),
)


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    present = _columns()
    for name, kind in _COLUMNS:
        if name not in present:
            op.add_column(_TABLE, sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    present = _columns()
    for name, _kind in reversed(_COLUMNS):
        if name in present:
            op.drop_column(_TABLE, name)
