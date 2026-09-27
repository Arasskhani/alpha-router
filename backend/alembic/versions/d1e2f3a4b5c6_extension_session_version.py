"""Record the package version each connected browser reports.

Revision ID: d1e2f3a4b5c6
Revises: c7e1a2b3d4f5
Create Date: 2026-09-27

Unpacked copies of the extension do not update themselves, so an
administrator needs to see who is still on an older package before requiring
the newest one. The browser sends its version when it connects and whenever it
refreshes its tokens; the column keeps the latest it reported.

Nullable, with no default: a browser that connected before this field existed
has none until it refreshes, and the overview counts it as unknown rather than
as old.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c7e1a2b3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "extension_sessions"
_COLUMN = "extension_version"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    if _COLUMN not in _columns():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=32), nullable=True))


def downgrade() -> None:
    if _COLUMN in _columns():
        op.drop_column(_TABLE, _COLUMN)
