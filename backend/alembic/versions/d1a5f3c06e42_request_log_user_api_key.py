"""request log user api key link

Revision ID: d1a5f3c06e42
Revises: c8d4e2b05f31
Create Date: 2026-08-17 15:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1a5f3c06e42"
down_revision: str | None = "c8d4e2b05f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("request_logs")}
    if "user_api_key_id" not in columns:
        op.add_column(
            "request_logs",
            sa.Column("user_api_key_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_request_logs_user_api_key_id",
            "request_logs",
            "user_api_keys",
            ["user_api_key_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_request_logs_user_api_key_id",
            "request_logs",
            ["user_api_key_id"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("request_logs")}
    if "user_api_key_id" in columns:
        op.drop_index("ix_request_logs_user_api_key_id", table_name="request_logs")
        op.drop_constraint(
            "fk_request_logs_user_api_key_id",
            "request_logs",
            type_="foreignkey",
        )
        op.drop_column("request_logs", "user_api_key_id")
