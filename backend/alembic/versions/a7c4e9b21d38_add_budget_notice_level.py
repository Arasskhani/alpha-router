"""Users: remember which budget warning has already been shown.

Revision ID: a7c4e9b21d38
Revises: 6d2e3f4a5b6c
Create Date: 2026-09-16

A user was told nothing as their monthly budget ran down; the first sign was
a request being refused. The platform now warns at 70% and 90%, and a warning
is only useful if it arrives once: without somewhere to record what has
already been said, every settled turn past the line would raise the same
toast again.

``budget_notice_level`` holds the highest threshold announced in the current
period (0, 70 or 90). It is kept in step with the live percentage in *both*
directions, so a plan increase or an administrator's budget reset lowers it
and the warning can fire again later in the same month. That also means the
three places that reset a budget period need no change: the value re-aligns
itself the next time usage is evaluated.

Not nullable, defaulting to 0: an existing user has been told nothing, which
is exactly what 0 means.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c4e9b21d38"
down_revision: str | None = "6d2e3f4a5b6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "budget_notice_level" not in existing:
        op.add_column(
            "users",
            sa.Column("budget_notice_level", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("users", "budget_notice_level")
