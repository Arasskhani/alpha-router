"""Feature Access governs creating projects and the browser extension too.

Revision ID: a4c6e8f0b2d3
Revises: f3c5e7a9b1d2
Create Date: 2026-10-07

Two more sections beside Chat, Projects and API keys:

- ``project_create``: creating a project. It is closed whenever Projects is,
  and whenever Chat is unless the person has their own Allow on it - so a
  person whose Chat is closed cannot open a project of their own to chat in.
- ``extension``: the browser extension - downloading it, connecting a
  browser, and every call a connected browser makes.

Only the check on ``feature`` changes. With no rules on the new sections,
the only change is the Chat link: people whose Chat is already closed can no
longer create projects.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c6e8f0b2d3"
down_revision: str | None = "f3c5e7a9b1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "feature_access_rules"
_CHECK = "chk_feature_access_feature"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(
            _CHECK, "feature IN ('chat', 'projects', 'api_keys', 'project_create', 'extension')"
        )


def downgrade() -> None:
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE feature IN ('project_create', 'extension')"))
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, "feature IN ('chat', 'projects', 'api_keys')")
