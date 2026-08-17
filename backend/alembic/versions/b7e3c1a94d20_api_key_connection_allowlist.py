"""api key connection allowlist

Revision ID: b7e3c1a94d20
Revises: f2a8c5d91b34
Create Date: 2026-08-17 11:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e3c1a94d20"
down_revision: str | None = "f2a8c5d91b34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    api_key_columns = {
        column["name"] for column in inspector.get_columns("alpha_router_api_keys")
    }
    if "restrict_connections" not in api_key_columns:
        op.add_column(
            "alpha_router_api_keys",
            sa.Column(
                "restrict_connections",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if "alpha_router_api_key_connections" not in inspector.get_table_names():
        op.create_table(
            "alpha_router_api_key_connections",
            sa.Column("alpha_router_api_key_id", sa.Integer(), nullable=False),
            sa.Column("connection_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["alpha_router_api_key_id"],
                ["alpha_router_api_keys.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["connection_id"],
                ["connections.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("alpha_router_api_key_id", "connection_id"),
        )
        op.create_index(
            "ix_alpha_router_api_key_connections_connection_id",
            "alpha_router_api_key_connections",
            ["connection_id"],
        )
    else:
        join_indexes = {
            index["name"]
            for index in inspector.get_indexes("alpha_router_api_key_connections")
        }
        if "ix_alpha_router_api_key_connections_connection_id" not in join_indexes:
            op.create_index(
                "ix_alpha_router_api_key_connections_connection_id",
                "alpha_router_api_key_connections",
                ["connection_id"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "alpha_router_api_key_connections" in inspector.get_table_names():
        join_indexes = {
            index["name"]
            for index in inspector.get_indexes("alpha_router_api_key_connections")
        }
        if "ix_alpha_router_api_key_connections_connection_id" in join_indexes:
            op.drop_index(
                "ix_alpha_router_api_key_connections_connection_id",
                table_name="alpha_router_api_key_connections",
            )
        op.drop_table("alpha_router_api_key_connections")

    api_key_columns = {
        column["name"] for column in inspector.get_columns("alpha_router_api_keys")
    }
    if "restrict_connections" in api_key_columns:
        op.drop_column("alpha_router_api_keys", "restrict_connections")
