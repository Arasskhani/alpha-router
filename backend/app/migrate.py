"""Database migration entrypoint used by deployment jobs and Docker Compose."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

import app.models  # noqa: F401
from app.database import Base, engine
from app.db_migrate import (
    apply_schema_column_patches,
    backfill_api_key_unlimited_budget,
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
    await backfill_api_key_unlimited_budget()
    await engine.dispose()


async def _validate() -> None:
    await validate_agent_platform_schema()
    await validate_accounting_schema()
    await engine.dispose()


_CONNECT_ATTEMPTS = 6
_CONNECT_BACKOFF_SECONDS = (1, 2, 4, 8, 15)


def _with_db_retry(step, label: str) -> None:
    """Retry ``step`` while the database is still coming up.

    ``db-init`` starts once postgres/pgbouncer report healthy, but the first
    connection through PgBouncer can still be refused for a moment (or the
    server is mid-recovery). One OperationalError used to fail the whole
    ``compose up`` and leave the operator with an unexplained exit code.
    """
    import time

    from sqlalchemy.exc import DBAPIError, OperationalError

    last: Exception | None = None
    for attempt in range(_CONNECT_ATTEMPTS):
        try:
            step()
            return
        except (OperationalError, DBAPIError, OSError, ConnectionError) as exc:
            last = exc
            if attempt + 1 >= _CONNECT_ATTEMPTS:
                break
            delay = _CONNECT_BACKOFF_SECONDS[min(attempt, len(_CONNECT_BACKOFF_SECONDS) - 1)]
            print(
                f"[migrate] {label}: database not ready ({type(exc).__name__}); retry {attempt + 1}/{_CONNECT_ATTEMPTS - 1} in {delay}s",
                flush=True,
            )
            time.sleep(delay)
    raise SystemExit(f"[migrate] {label} failed after {_CONNECT_ATTEMPTS} attempts: {last}")


def main() -> None:
    _with_db_retry(lambda: asyncio.run(_bootstrap_legacy_schema()), "legacy schema bootstrap")
    _with_db_retry(lambda: upgrade_schema_sync("head"), "alembic upgrade")
    _with_db_retry(lambda: asyncio.run(_validate()), "schema validation")


if __name__ == "__main__":
    main()
