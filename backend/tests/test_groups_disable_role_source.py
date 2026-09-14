"""Group disable-members must honor user_role_assignments as sole RBAC source."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.groups import _disable_users_skipping_admins
from app.database import Base
from app.models.user import User, UserRoleAssignment
from app.services.rbac import DASHBOARD_VIEW_SLUG, USER_SLUG
from app.services.user_role_service import get_user_role_slugs, set_user_roles


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def test_disable_skips_admin_from_assignments():
    async def run():
        Session, engine = await _session_factory()
        try:
            async with Session() as db:
                adminish = User(
                    username="sara",
                    hashed_password="x",
                    auth_provider="local",
                    is_active=True,
                )
                regular = User(
                    username="bob",
                    hashed_password="x",
                    auth_provider="local",
                    is_active=True,
                )
                db.add_all([adminish, regular])
                await db.flush()
                await set_user_roles(db, adminish, [DASHBOARD_VIEW_SLUG])

                disabled, skipped = await _disable_users_skipping_admins(db, [adminish, regular])
                await db.commit()

                assert skipped == 1
                assert disabled == 1
                assert adminish.is_active is True
                assert regular.is_active is False
                assert int(regular.token_version or 0) >= 1
                assert await get_user_role_slugs(db, adminish.id) == [DASHBOARD_VIEW_SLUG]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_get_user_role_slugs_defaults_without_assignments():
    async def run():
        Session, engine = await _session_factory()
        try:
            async with Session() as db:
                user = User(
                    username="plain",
                    hashed_password="x",
                    auth_provider="local",
                    is_active=True,
                )
                db.add(user)
                await db.flush()
                assert await get_user_role_slugs(db, user.id) == [USER_SLUG]

                db.add(UserRoleAssignment(user_id=user.id, role_slug=DASHBOARD_VIEW_SLUG))
                await db.flush()
                assert await get_user_role_slugs(db, user.id) == [DASHBOARD_VIEW_SLUG]
        finally:
            await engine.dispose()

    asyncio.run(run())
