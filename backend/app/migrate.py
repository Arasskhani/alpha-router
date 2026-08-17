"""Database migration entrypoint used by deployment jobs and Docker Compose."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

import app.models  # noqa: F401
from app.database import Base, engine
from app.db_migrate import (
    apply_schema_column_patches,
    validate_accounting_schema,
    validate_agent_platform_schema,
)
from app.schema_migrations import upgrade_schema_sync
from app.schema_registry import legacy_metadata_tables


async def _bootstrap_legacy_schema() -> None:
    """Keep existing installations compatible while Alembic takes ownership."""

    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(56023113)"))
        await conn.run_sync(
            Base.metadata.create_all,
            tables=legacy_metadata_tables(Base.metadata),
        )
    await apply_schema_column_patches()
    await engine.dispose()


async def _validate() -> None:
    await validate_agent_platform_schema()
    await validate_accounting_schema()
    await engine.dispose()


def main() -> None:
    asyncio.run(_bootstrap_legacy_schema())
    upgrade_schema_sync("head")
    asyncio.run(_validate())


if __name__ == "__main__":
    main()
