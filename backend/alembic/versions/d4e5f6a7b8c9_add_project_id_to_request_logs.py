"""add project_id to request_logs for cost attribution

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-19 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    existing_columns = {c["name"] for c in inspector.get_columns("request_logs")}
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("request_logs")}
    existing_fks = {
        fk["name"]
        for fk in inspector.get_foreign_keys("request_logs")
        if fk.get("name")
    }

    if "project_id" not in existing_columns:
        if dialect == "sqlite":
            with op.batch_alter_table("request_logs") as batch:
                batch.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        else:
            op.add_column(
                "request_logs",
                sa.Column("project_id", sa.String(length=36), nullable=True),
            )

    if "ix_request_logs_project_id" not in existing_indexes:
        op.create_index(
            "ix_request_logs_project_id",
            "request_logs",
            ["project_id"],
        )

    fk_name = "fk_request_logs_project_id"
    if fk_name not in existing_fks and dialect != "sqlite":
        op.create_foreign_key(
            fk_name,
            "request_logs",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
    elif dialect == "sqlite" and fk_name not in existing_fks:
        with op.batch_alter_table("request_logs") as batch:
            batch.create_foreign_key(
                fk_name,
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    existing_fks = {
        fk["name"]
        for fk in inspector.get_foreign_keys("request_logs")
        if fk.get("name")
    }
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("request_logs")}
    existing_columns = {c["name"] for c in inspector.get_columns("request_logs")}

    fk_name = "fk_request_logs_project_id"
    if fk_name in existing_fks:
        if dialect == "sqlite":
            with op.batch_alter_table("request_logs") as batch:
                batch.drop_constraint(fk_name, type_="foreignkey")
        else:
            op.drop_constraint(fk_name, "request_logs", type_="foreignkey")

    if "ix_request_logs_project_id" in existing_indexes:
        op.drop_index("ix_request_logs_project_id", table_name="request_logs")

    if "project_id" in existing_columns:
        if dialect == "sqlite":
            with op.batch_alter_table("request_logs") as batch:
                batch.drop_column("project_id")
        else:
            op.drop_column("request_logs", "project_id")
