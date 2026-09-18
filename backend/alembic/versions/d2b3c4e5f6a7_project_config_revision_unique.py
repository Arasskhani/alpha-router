"""Project config versions: one row per revision number.

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-09-18

``update_project_config`` allocates ``revision`` as ``MAX(revision) + 1`` with
no lock. Every other MAX()+1 in this codebase has a unique constraint behind it
- knowledge releases, document versions, agent versions, chat message sequence -
and this one had only ``ix_project_config_versions_project``.

So two owners saving Advanced settings at the same moment both read the same
maximum and both wrote it. The result is two rows claiming one revision of a
history the product describes as immutable and reproducible, with
``projects.active_config_version_id`` resolving last-write-wins: one owner's
prompt or grounding policy is silently discarded while its version row stays in
the list.

Existing duplicates are renumbered before the constraint is added, oldest first,
so the upgrade cannot fail on data that predates it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2b3c4e5f6a7"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "project_config_versions"
_CONSTRAINT = "uq_project_config_versions_revision"


def _renumber_duplicates(bind: sa.engine.Connection) -> None:
    """Give every row a distinct revision within its project, oldest first."""

    rows = bind.execute(
        sa.text(
            f"SELECT id, project_id, revision FROM {_TABLE} "  # noqa: S608 - fixed identifier
            "ORDER BY project_id, revision, created_at, id"
        )
    ).fetchall()
    next_by_project: dict[str, int] = {}
    for row_id, project_id, revision_value in rows:
        expected = next_by_project.get(project_id, 1)
        if int(revision_value or 0) != expected:
            bind.execute(
                sa.text(f"UPDATE {_TABLE} SET revision = :rev WHERE id = :id"),  # noqa: S608
                {"rev": expected, "id": row_id},
            )
        next_by_project[project_id] = expected + 1


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_unique_constraints(_TABLE)}
    if _CONSTRAINT in existing:
        return
    _renumber_duplicates(bind)
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_CONSTRAINT, ["project_id", "revision"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _CONSTRAINT not in {c["name"] for c in inspector.get_unique_constraints(_TABLE)}:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="unique")
