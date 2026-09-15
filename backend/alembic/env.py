"""Alembic environment for versioned Alpharouter schema migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401
from alembic import context
from app.config import get_settings
from app.database import Base, asyncpg_connect_args
from app.schema_registry import AGENT_PLATFORM_TABLE_NAMES

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


# Used only to generate the first Agent Platform revision against an empty
# database. Normal migration generation compares every ORM table.
def _include_object(obj, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    if os.getenv("ALEMBIC_AGENT_PLATFORM_ONLY") != "1":
        return True
    if type_ == "table":
        return bool(name in AGENT_PLATFORM_TABLE_NAMES)
    table_name = getattr(getattr(obj, "table", None), "name", None)
    return bool(table_name in AGENT_PLATFORM_TABLE_NAMES)


def _configure(connection: Connection | None = None, *, url: str | None = None) -> None:
    kwargs = {
        "target_metadata": target_metadata,
        "include_object": _include_object,
        "compare_type": True,
        "compare_server_default": True,
        "render_as_batch": connection is not None and connection.dialect.name == "sqlite",
    }
    if connection is not None:
        context.configure(connection=connection, **kwargs)
    else:
        context.configure(
            url=url,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            **kwargs,
        )


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine_kwargs: dict = {"poolclass": pool.NullPool}
    if not settings.database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = asyncpg_connect_args()
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        **engine_kwargs,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
