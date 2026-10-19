"""Connections get a kind: model providers, or web search providers.

Revision ID: b7d9f1a3c5e7
Revises: a4c6e8f0b2d3
Create Date: 2026-10-19

- ``kind``: ``models`` (every existing connection) or ``web_search``. Set when
  a connection is made and never changed, so a search key can never be sent
  to a model provider or synced for models, and the other way round.
- ``config_json``: provider options that are not a key (Google's engine id).
- ``priority``: the order web search connections are tried in.
- ``price_per_request_usd``: what one search costs the person's budget.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d9f1a3c5e7"
down_revision: str | None = "a4c6e8f0b2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "connections"
_CHECK = "chk_connections_kind"
_INDEX = "ix_connections_kind"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(length=16), nullable=False, server_default="models"))
        batch_op.add_column(sa.Column("config_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
        batch_op.add_column(
            sa.Column(
                "price_per_request_usd",
                sa.Numeric(precision=20, scale=12, asdecimal=False),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_index(_INDEX, ["kind"], unique=False)
        batch_op.create_check_constraint(_CHECK, "kind IN ('models', 'web_search')")


def downgrade() -> None:
    # A web search connection has no meaning to the older code, which would take it for a model provider.
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE kind = 'web_search'"))
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.drop_index(_INDEX)
        batch_op.drop_column("price_per_request_usd")
        batch_op.drop_column("priority")
        batch_op.drop_column("config_json")
        batch_op.drop_column("kind")
