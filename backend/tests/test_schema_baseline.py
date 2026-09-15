"""Schema drift gate (Phase 4.3): the migration chain alone must produce the ORM.

Runs only against PostgreSQL (``DATABASE_URL`` pointing at a Postgres server,
as in the ``backend-postgres-canary`` CI job). It creates a scratch database,
runs ``alembic upgrade head`` on it — no ``create_all``, no column patches —
and asks Alembic's autogenerate what it would still change. The answer must
be *nothing*. When this fails, the fix is a new revision (or an ORM change
that matches an existing one), never editing the baseline.

Server defaults are not compared (the ORM sets defaults in Python), and the
trigram GIN indexes created with raw SQL are skipped because SQLAlchemy has
no ORM-side representation of them.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

import app.models as _orm_models  # noqa: F401
from app.database import Base

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(
    not _DATABASE_URL.startswith("postgresql"),
    reason="schema drift gate runs against PostgreSQL only (set DATABASE_URL)",
)


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "index" and name and name.endswith("_trgm"))


def _admin_url() -> str:
    # Connect to the maintenance database to create/drop the scratch one.
    base, _, _dbname = _DATABASE_URL.rpartition("/")
    return f"{base}/postgres"


async def _with_scratch_database(fn):
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    name = f"alpharouter_drift_{uuid.uuid4().hex[:8]}"
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    try:
        base, _, _ = _DATABASE_URL.rpartition("/")
        await fn(f"{base}/{name}")
    finally:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_alembic_chain_reproduces_the_orm_exactly() -> None:
    async def check(url: str) -> None:
        config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
        config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            from app import config as app_config

            app_config.get_settings.cache_clear()
            # alembic's env.py opens its own event loop; run it in a thread.
            import asyncio

            await asyncio.to_thread(command.upgrade, config, "head")
        finally:
            if previous is not None:
                os.environ["DATABASE_URL"] = previous
            app_config.get_settings.cache_clear()

        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:

                def compare(sync_conn):
                    ctx = MigrationContext.configure(
                        sync_conn,
                        opts={
                            "compare_type": True,
                            "compare_server_default": False,
                            "include_object": _include_object,
                            "target_metadata": Base.metadata,
                        },
                    )
                    return compare_metadata(ctx, Base.metadata)

                diffs = await conn.run_sync(compare)
        finally:
            await engine.dispose()

        rendered = [str(d[0] if isinstance(d, list) else d)[:200] for d in diffs]
        assert not diffs, "ORM and migration chain disagree:\n" + "\n".join(rendered)

    await _with_scratch_database(check)
