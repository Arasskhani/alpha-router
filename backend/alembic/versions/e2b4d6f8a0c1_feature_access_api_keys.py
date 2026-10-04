"""Feature Access governs personal API keys too.

Revision ID: e2b4d6f8a0c1
Revises: d7f1a3c5e9b2
Create Date: 2026-10-04

A third section beside Chat and Projects: closed for a person, they cannot
make a personal API key, and the keys they already have are refused at the
gateway (kept, not revoked: they work again when the section opens). Only
the check on ``feature`` changes; with no rules nothing changes for anybody.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2b4d6f8a0c1"
down_revision: str | None = "d7f1a3c5e9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "feature_access_rules"
_CHECK = "chk_feature_access_feature"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, "feature IN ('chat', 'projects', 'api_keys')")


def downgrade() -> None:
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE feature = 'api_keys'"))
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, "feature IN ('chat', 'projects')")
