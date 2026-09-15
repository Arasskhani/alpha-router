"""Money columns: Float -> Numeric.

Revision ID: 5c1d2e3f4a5b
Revises: 4b0c1d2e3f4a
Create Date: 2026-09-14

Phase 4.2. Balances, holds, credit limits and per-request costs were
``double precision``; every SQL-side increment (``budget_used_usd =
budget_used_usd + :x``) accumulated binary rounding error and the periodic
reconciliation had to paper over it. They become ``NUMERIC(20, 12)``
(catalog prices ``NUMERIC(24, 14)``); the ORM reads them back as float
(``asdecimal=False``) so callers are unchanged.

``USING col::numeric`` rounds each stored double to 12 places, which is the
value the application always meant. SQLite has no column types to alter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c1d2e3f4a5b"
down_revision: str | None = "4b0c1d2e3f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY: tuple[tuple[str, str], ...] = (
    ("alpha_router_api_keys", "credit_limit_usd"),
    ("alpha_router_api_keys", "period_used_usd"),
    ("alpha_router_api_keys", "period_reserved_usd"),
    ("alpha_router_api_keys", "total_used_usd"),
    ("budget_plans", "monthly_budget_usd"),
    ("budget_reservations", "reserved_usd"),
    ("budget_reservations", "actual_usd"),
    ("request_logs", "total_cost_usd"),
    ("request_logs", "provider_cost_usd"),
    ("request_logs", "calculated_cost_usd"),
    ("users", "monthly_budget_usd"),
    ("users", "budget_used_usd"),
    ("users", "budget_reserved_usd"),
)
_PRICE: tuple[tuple[str, str], ...] = (
    ("ai_models", "input_cost_per_1k"),
    ("ai_models", "output_cost_per_1k"),
)


def _alter(table: str, column: str, precision: int, scale: int) -> None:
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC({precision}, {scale}) "
        f"USING ROUND({column}::numeric, {scale})"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column in _MONEY:
        if table in tables:
            _alter(table, column, 20, 12)
    for table, column in _PRICE:
        if table in tables:
            _alter(table, column, 24, 14)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, column in _MONEY + _PRICE:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE DOUBLE PRECISION USING {column}::double precision")
