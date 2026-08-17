"""api key model allowlist

Revision ID: c8d4e2b05f31
Revises: b7e3c1a94d20
Create Date: 2026-08-17 13:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8d4e2b05f31"
down_revision: str | None = "b7e3c1a94d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    api_key_columns = {
        column["name"] for column in inspector.get_columns("alpha_router_api_keys")
    }
    if "restrict_models" not in api_key_columns:
        op.add_column(
            "alpha_router_api_keys",
            sa.Column(
                "restrict_models",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if "alpha_router_api_key_models" not in inspector.get_table_names():
        op.create_table(
            "alpha_router_api_key_models",
            sa.Column("alpha_router_api_key_id", sa.Integer(), nullable=False),
            sa.Column("model_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["alpha_router_api_key_id"],
                ["alpha_router_api_keys.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["model_id"],
                ["ai_models.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("alpha_router_api_key_id", "model_id"),
        )
        op.create_index(
            "ix_alpha_router_api_key_models_model_id",
            "alpha_router_api_key_models",
            ["model_id"],
        )
    else:
        join_indexes = {
            index["name"] for index in inspector.get_indexes("alpha_router_api_key_models")
        }
        if "ix_alpha_router_api_key_models_model_id" not in join_indexes:
            op.create_index(
                "ix_alpha_router_api_key_models_model_id",
                "alpha_router_api_key_models",
                ["model_id"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "alpha_router_api_key_models" in inspector.get_table_names():
        join_indexes = {
            index["name"] for index in inspector.get_indexes("alpha_router_api_key_models")
        }
        if "ix_alpha_router_api_key_models_model_id" in join_indexes:
            op.drop_index(
                "ix_alpha_router_api_key_models_model_id",
                table_name="alpha_router_api_key_models",
            )
        op.drop_table("alpha_router_api_key_models")

    api_key_columns = {
        column["name"] for column in inspector.get_columns("alpha_router_api_keys")
    }
    if "restrict_models" in api_key_columns:
        op.drop_column("alpha_router_api_keys", "restrict_models")
