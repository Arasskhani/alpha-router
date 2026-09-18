"""Shared test fixtures (Phase 3.2).

Tests are native ``async def`` (pytest-asyncio, ``asyncio_mode = auto`` in
pytest.ini); ``asyncio.run`` inside a test is reserved for the few tests that
deliberately need two event loops.

Fixtures:

``engine``      the database named by ``TEST_DATABASE_URL``, else SQLite
                in-memory, with every ORM table created. Function-scoped: each
                test starts from an empty schema. SQLite runs with
                ``PRAGMA foreign_keys=ON`` so that ``ON DELETE`` clauses behave
                as they do on PostgreSQL; ``backend-tests-postgres`` in CI sets
                ``TEST_DATABASE_URL`` so the locking and trigger behaviour that
                SQLite cannot express is exercised for real.
``db_session``  one ``AsyncSession`` on that engine (``expire_on_commit=False``).
``session_factory``  the ``async_sessionmaker`` when a test needs several sessions.
``client``      ``httpx.AsyncClient`` over the real FastAPI app with ``get_db``
                overridden to the test engine (no network, no lifespan).
``user`` / ``admin``  a plain active local user and a Full Administrator, committed.

New tests should use these instead of copying ``create_async_engine`` blocks;
existing tests keep their local helpers until they are touched.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

import app.models as _orm_models  # noqa: F401 -- registers every ORM table on Base.metadata
from app.database import Base, enable_sqlite_foreign_keys

_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


async def _reset_schema(conn) -> None:
    """Empty the database the hard way.

    ``Base.metadata.drop_all`` cannot do this on PostgreSQL: the schema contains
    ``use_alter`` foreign keys, which SQLAlchemy drops with an unconditional
    ``ALTER TABLE ... DROP CONSTRAINT`` that fails when the table is already
    gone. Dropping the schema is both correct and faster.
    """

    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = _TEST_DATABASE_URL or "sqlite+aiosqlite:///:memory:"
    eng = enable_sqlite_foreign_keys(create_async_engine(url))
    async with eng.begin() as conn:
        if _TEST_DATABASE_URL:
            await _reset_schema(conn)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        if _TEST_DATABASE_URL:
            async with eng.begin() as conn:
                await _reset_schema(conn)
        await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def user(db_session: AsyncSession):
    from app.core.security import hash_password
    from app.models.user import User

    row = User(
        username="fixture_user",
        email="fixture_user@test",
        hashed_password=hash_password("fixture-user-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def admin(db_session: AsyncSession):
    from app.core.security import hash_password
    from app.models.user import User
    from app.services.user_role_service import ensure_super_admin_roles

    row = User(
        username="fixture_admin",
        email="fixture_admin@test",
        hashed_password=hash_password("fixture-admin-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    await ensure_super_admin_roles(db_session, row, admin_username="fixture_admin")
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]):
    """The FastAPI app over ASGI with the database dependency pointed at the test engine."""
    import httpx

    from app.database import get_db
    from app.main import app as fastapi_app

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _get_db
    try:
        transport = httpx.ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
