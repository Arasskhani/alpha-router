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


async def apply_sqlite_schema_patches() -> None:
    """Apply current-schema patches only for a configured SQLite database."""
    if "sqlite" not in get_settings().database_url:
        return
    await apply_schema_column_patches()
