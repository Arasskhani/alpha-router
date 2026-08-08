"""LDAP OU prune moves users to Deleted Users instead of hard delete."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.user_lifecycle_service import prune_sync_user


async def _run_prune_soft_deletes_without_login_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        user = User(
            username="ldap.user",
            email="ldap.user@test",
            hashed_password="",
            auth_provider="ldap",
            external_id="CN=ldap.user,OU=Old,DC=test,DC=local",
            is_active=True,
        )
        db.add(user)
        await db.commit()

        user = (await db.execute(select(User))).scalar_one()
        action = await prune_sync_user(db, user)
        assert action == "soft_deleted"

        await db.commit()
        await db.refresh(user)
        assert user.deleted_at is not None
        assert user.is_active is False

        still_there = (await db.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
        assert still_there is not None


def test_prune_sync_user_soft_deletes_even_without_last_login():
    asyncio.run(_run_prune_soft_deletes_without_login_history())
