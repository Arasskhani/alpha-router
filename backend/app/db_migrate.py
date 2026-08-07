"""Schema synchronization for PostgreSQL production and SQLite tests."""

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex

from app.config import get_settings
from app.database import Base, engine


def _ensure_missing_indexes(connection, table, inspector) -> None:
    """Create ORM indexes absent from an existing table."""
    existing = {
        index["name"]
        for index in inspector.get_indexes(table.name)
        if index.get("name")
    }
    for index in table.indexes:
        if not index.name or index.name in existing:
            continue
        connection.execute(CreateIndex(index))


async def apply_schema_column_patches() -> None:
    """Add ORM columns and indexes missing from existing current-schema tables.

    Multiple workers serialize discovery and DDL with a PostgreSQL advisory
    lock.  Duplicate-column errors are tolerated only for the race where
    another worker completed the same patch first.
    """
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(56023113)"))

        def patch(connection) -> None:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            for table in Base.metadata.sorted_tables:
                if table.name not in tables:
                    continue
                existing = {
                    column["name"] for column in inspector.get_columns(table.name)
                }
                for column in table.columns:
                    if column.name in existing:
                        continue
                    ddl = column.type.compile(dialect=connection.dialect)
                    try:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table.name} "
                                f"ADD COLUMN {column.name} {ddl}"
                            )
                        )
                    except Exception as exc:
                        message = str(exc).lower()
                        if (
                            "already exists" in message
                            or "duplicate column" in message
                        ):
                            continue
                        raise
                _ensure_missing_indexes(connection, table, inspector)

        await conn.run_sync(patch)


async def validate_accounting_schema() -> None:
    """Fail readiness when required accounting storage is incomplete."""

    required = {
        "pricing_snapshots": {
            "provider_type",
            "service_type",
            "active_scope_key",
            "pricing_json",
        },
        "usage_operations": {
            "idempotency_key",
            "accounting_status",
            "total_cost_usd",
        },
        "usage_events": {
            "operation_id",
            "final_cost_usd",
            "cost_source",
            "cost_confidence",
            "reconciliation_attempts",
        },
        "cost_line_items": {"usage_event_id", "quantity", "unit", "cost_usd"},
        "cost_ledger_entries": {
            "operation_id",
            "amount_usd",
            "idempotency_key",
            "effective_at",
        },
        "reconciliation_runs": {"provider_type", "status", "adjustment_usd"},
        "request_logs": {
            "usage_operation_id",
            "cost_source",
            "cost_confidence",
            "has_unpriced_usage",
        },
    }

    async with engine.connect() as conn:
        def validate(connection) -> list[str]:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            missing: list[str] = []
            for table_name, expected_columns in required.items():
                if table_name not in tables:
                    missing.append(f"table:{table_name}")
                    continue
                present = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }
                missing.extend(
                    f"column:{table_name}.{column}"
                    for column in sorted(expected_columns - present)
                )
            return missing

        missing = await conn.run_sync(validate)
    if missing:
        raise RuntimeError(
            "Accounting schema is incomplete: " + ", ".join(missing)
        )


async def apply_sqlite_schema_patches() -> None:
    """Apply current-schema patches only for a configured SQLite database."""
    if "sqlite" not in get_settings().database_url:
        return
    await apply_schema_column_patches()
