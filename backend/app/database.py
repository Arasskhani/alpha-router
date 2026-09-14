"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from sqlalchemy import Numeric
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


def asyncpg_connect_args() -> dict[str, Any]:
    """Connect args every asyncpg engine needs behind PgBouncer.

    Transaction pooling multiplexes clients onto shared server connections, so
    cached or deterministically named prepared statements collide. Alembic and
    any other engine outside this module must reuse these args.
    """

    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


_engine_kwargs: dict = {"echo": settings.debug}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        connect_args=asyncpg_connect_args(),
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)

read_engine = None
AsyncReadSessionLocal: async_sessionmaker[AsyncSession] | None = None
if settings.database_read_url and not settings.database_read_url.startswith("sqlite"):
    read_engine = create_async_engine(
        settings.database_read_url,
        pool_pre_ping=True,
        pool_size=max(5, settings.db_pool_size // 2),
        max_overflow=max(10, settings.db_max_overflow // 2),
        pool_timeout=settings.db_pool_timeout,
        echo=settings.debug,
        connect_args=asyncpg_connect_args(),
    )
    AsyncReadSessionLocal = async_sessionmaker(read_engine, class_=AsyncSession, expire_on_commit=False)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """Read session: uses DATABASE_READ_URL when configured, else primary."""
    factory = AsyncReadSessionLocal or AsyncSessionLocal
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# --- Money column types (Phase 4.2) -----------------------------------------
# Balances, holds, limits and per-request costs are stored as exact decimals
# so SQL-side arithmetic (``budget_used_usd = budget_used_usd + :x``) never
# accumulates binary-float error. ``asdecimal=False`` keeps the Python side on
# floats: the accounting code, the JSON API and the tests all speak float, and
# the rounding on the way in (12 places) is far below any billing unit.
# Ledger tables (``usage_events`` etc.) already use Numeric(20, 12) with
# Decimal results and are the source of truth for reconciliation.
MoneyUSD = Numeric(20, 12, asdecimal=False)
UnitPriceUSD = Numeric(24, 14, asdecimal=False)
