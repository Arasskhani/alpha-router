"""add project primary_owner role

Revision ID: b7c8d9e0f1a2
Revises: a8b9c0d1e2f3
Create Date: 2026-08-19 18:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ROLE_CHECK = (
    "role IN ('primary_owner', 'owner', 'contributor', 'viewer')"
)
_OLD_ROLE_CHECK = "role IN ('owner', 'contributor', 'viewer')"


def _table_exists(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def _index_exists(inspector, table: str, index: str) -> bool:
    return index in {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def _check_exists(inspector, table: str, name: str) -> bool:
    return name in {
        chk.get("name") for chk in inspector.get_check_constraints(table) if chk.get("name")
    }


def _replace_role_check(bind, new_sql: str) -> None:
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "project_members"):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("project_members") as batch_op:
            if _check_exists(inspector, "project_members", "chk_project_members_role"):
                batch_op.drop_constraint("chk_project_members_role", type_="check")
            batch_op.create_check_constraint("chk_project_members_role", new_sql)
        return
    if _check_exists(inspector, "project_members", "chk_project_members_role"):
        op.drop_constraint("chk_project_members_role", "project_members", type_="check")
    op.create_check_constraint("chk_project_members_role", "project_members", new_sql)


def _backfill_primary_owners(connection) -> None:
    inspector = sa.inspect(connection)
    if not _table_exists(inspector, "projects") or not _table_exists(inspector, "project_members"):
        return
    projects = connection.execute(
        sa.text("SELECT id, created_by_user_id FROM projects")
    ).fetchall()
    for project_id, creator_id in projects:
        existing = connection.execute(
            sa.text(
                "SELECT 1 FROM project_members "
                "WHERE project_id = :p AND role = 'primary_owner' LIMIT 1"
            ),
            {"p": project_id},
        ).fetchone()
        if existing:
            continue
        promoted = False
        if creator_id is not None:
            result = connection.execute(
                sa.text(
                    "UPDATE project_members SET role = 'primary_owner' "
                    "WHERE project_id = :p AND user_id = :u AND role = 'owner'"
                ),
                {"p": project_id, "u": creator_id},
            )
            promoted = bool(result.rowcount)
        if promoted:
            continue
        successor = connection.execute(
            sa.text(
                "SELECT user_id FROM project_members WHERE project_id = :p "
                "ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END, created_at, user_id "
                "LIMIT 1"
            ),
            {"p": project_id},
        ).fetchone()
        if successor is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE project_members SET role = 'primary_owner' "
                "WHERE project_id = :p AND user_id = :u"
            ),
            {"p": project_id, "u": successor[0]},
        )


def upgrade() -> None:
    bind = op.get_bind()
    _replace_role_check(bind, _NEW_ROLE_CHECK)
    _backfill_primary_owners(bind)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_members") and not _index_exists(
        inspector, "project_members", "uq_project_members_one_primary_owner"
    ):
        op.create_index(
            "uq_project_members_one_primary_owner",
            "project_members",
            ["project_id"],
            unique=True,
            sqlite_where=sa.text("role = 'primary_owner'"),
            postgresql_where=sa.text("role = 'primary_owner'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "project_members") and _index_exists(
        inspector, "project_members", "uq_project_members_one_primary_owner"
    ):
        op.drop_index("uq_project_members_one_primary_owner", table_name="project_members")

    if _table_exists(inspector, "project_members"):
        bind.execute(
            sa.text(
                "UPDATE project_members SET role = 'owner' WHERE role = 'primary_owner'"
            )
        )
    _replace_role_check(bind, _OLD_ROLE_CHECK)
