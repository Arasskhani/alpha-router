"""Public/Private catalog model access control."""

import asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import AlphaRouterApiKey
from app.models.connection import Connection
from app.models.model_catalog import AIModel, ModelAccessAssignment
from app.models.user import User, UserGroup, UserRoleAssignment, user_group_members
from app.services.model_access_service import (
    ACCESS_PRIVATE,
    ACCESS_PUBLIC,
    bulk_set_access_type,
    filter_models_for_subject,
    resolve_access_subject,
    set_model_access,
    user_can_access_model,
)
from app.services.model_sync import sync_connection_models
from app.services.rbac import SUPER_ADMIN_SLUG, USER_SLUG


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db: AsyncSession, username: str, *, role: str = USER_SLUG) -> User:
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    db.add(UserRoleAssignment(user_id=u.id, role_slug=role))
    await db.flush()
    return u


async def _conn(db: AsyncSession) -> Connection:
    c = Connection(
        name="or",
        provider_type="openrouter",
        api_key_encrypted="enc",
        is_active=True,
    )
    db.add(c)
    await db.flush()
    return c


async def _model(db: AsyncSession, conn: Connection, ext: str, *, access: str = ACCESS_PUBLIC) -> AIModel:
    m = AIModel(
        connection_id=conn.id,
        external_id=ext,
        display_name=ext,
        provider_type="openrouter",
        is_enabled=True,
        access_type=access,
    )
    db.add(m)
    await db.flush()
    return m


async def _test_public_visible_to_regular_user() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db, "alice")
        conn = await _conn(db)
        model = await _model(db, conn, "openai/gpt-4o")
        await db.commit()
        subject = await resolve_access_subject(db, user_id=user.id)
        assert await user_can_access_model(db, model, subject)
        filtered = await filter_models_for_subject(db, [model], subject)
        assert [m.id for m in filtered] == [model.id]
    await engine.dispose()


async def _test_private_user_and_group_assignment() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner = await _user(db, "owner")
        outsider = await _user(db, "outsider")
        member = await _user(db, "member")
        group = UserGroup(name="eng", source="local")
        db.add(group)
        await db.flush()
        await db.execute(user_group_members.insert().values(user_id=member.id, group_id=group.id))
        conn = await _conn(db)
        model = await _model(db, conn, "openai/gpt-4o", access=ACCESS_PRIVATE)
        await set_model_access(db, model, access_type=ACCESS_PRIVATE, user_ids=[owner.id], group_ids=[group.id])
        await db.commit()

        assert await user_can_access_model(db, model, await resolve_access_subject(db, user_id=owner.id))
        assert await user_can_access_model(db, model, await resolve_access_subject(db, user_id=member.id))
        assert not await user_can_access_model(db, model, await resolve_access_subject(db, user_id=outsider.id))
    await engine.dispose()


async def _test_private_empty_super_admin_only() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db, "alice")
        admin = await _user(db, "root", role=SUPER_ADMIN_SLUG)
        conn = await _conn(db)
        model = await _model(db, conn, "openai/secret", access=ACCESS_PRIVATE)
        await set_model_access(db, model, access_type=ACCESS_PRIVATE, user_ids=[], group_ids=[])
        await db.commit()

        assert not await user_can_access_model(db, model, await resolve_access_subject(db, user_id=user.id))
        assert await user_can_access_model(db, model, await resolve_access_subject(db, user_id=admin.id))
        filtered = await filter_models_for_subject(db, [model], await resolve_access_subject(db, user_id=user.id))
        assert filtered == []
    await engine.dispose()


async def _test_bulk_public_clears_assignments_private_keeps() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db, "alice")
        conn = await _conn(db)
        a = await _model(db, conn, "a", access=ACCESS_PRIVATE)
        b = await _model(db, conn, "b", access=ACCESS_PRIVATE)
        await set_model_access(db, a, access_type=ACCESS_PRIVATE, user_ids=[user.id])
        await set_model_access(db, b, access_type=ACCESS_PRIVATE, user_ids=[user.id])
        await db.commit()

        await bulk_set_access_type(db, [a.id, b.id], ACCESS_PRIVATE)
        await db.commit()
        still = (
            (await db.execute(select(ModelAccessAssignment).where(ModelAccessAssignment.model_id == a.id)))
            .scalars()
            .all()
        )
        assert len(still) == 1
        await db.refresh(a)
        assert a.access_type == ACCESS_PRIVATE

        await bulk_set_access_type(db, [a.id, b.id], ACCESS_PUBLIC)
        await db.commit()
        cleared = (
            (await db.execute(select(ModelAccessAssignment).where(ModelAccessAssignment.model_id.in_([a.id, b.id]))))
            .scalars()
            .all()
        )
        assert cleared == []
        await db.refresh(a)
        await db.refresh(b)
        assert a.access_type == ACCESS_PUBLIC
        assert b.access_type == ACCESS_PUBLIC
    await engine.dispose()


async def _test_master_and_alpha_router_key_subjects() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner = await _user(db, "owner")
        conn = await _conn(db)
        pub = await _model(db, conn, "public-model")
        priv = await _model(db, conn, "private-model", access=ACCESS_PRIVATE)
        await set_model_access(db, priv, access_type=ACCESS_PRIVATE, user_ids=[owner.id])
        key = AlphaRouterApiKey(
            name="k1",
            key_prefix="alpha_router_",
            key_hash="hash",
            owner_user_id=owner.id,
            is_active=True,
        )
        orphan = AlphaRouterApiKey(
            name="k2",
            key_prefix="alpha_router_",
            key_hash="hash2",
            owner_user_id=None,
            is_active=True,
        )
        db.add(key)
        db.add(orphan)
        await db.commit()

        master = await resolve_access_subject(db, source="master")
        assert master.public_only
        assert await user_can_access_model(db, pub, master)
        assert not await user_can_access_model(db, priv, master)

        owned = await resolve_access_subject(
            db,
            alpha_router_api_key_id=key.id,
        )
        assert await user_can_access_model(db, priv, owned)

        orphan_subj = await resolve_access_subject(
            db,
            alpha_router_api_key_id=orphan.id,
        )
        assert orphan_subj.public_only
        assert not await user_can_access_model(db, priv, orphan_subj)
    await engine.dispose()


async def _test_sync_preserves_access_type() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _conn(db)
        model = await _model(db, conn, "openai/gpt-4o", access=ACCESS_PRIVATE)
        await set_model_access(db, model, access_type=ACCESS_PRIVATE, user_ids=[])
        await db.commit()

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "openai/gpt-4o",
                        "name": "GPT-4o Updated",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    }
                ]
            ),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        await db.refresh(model)
        assert model.access_type == ACCESS_PRIVATE
        assert model.display_name == "GPT-4o Updated"
        assigns = (
            (await db.execute(select(ModelAccessAssignment).where(ModelAccessAssignment.model_id == model.id)))
            .scalars()
            .all()
        )
        assert assigns == []
    await engine.dispose()


def test_public_visible_to_regular_user():
    asyncio.run(_test_public_visible_to_regular_user())


def test_private_user_and_group_assignment():
    asyncio.run(_test_private_user_and_group_assignment())


def test_private_empty_super_admin_only():
    asyncio.run(_test_private_empty_super_admin_only())


def test_bulk_public_clears_assignments_private_keeps():
    asyncio.run(_test_bulk_public_clears_assignments_private_keeps())


def test_master_and_alpha_router_key_subjects():
    asyncio.run(_test_master_and_alpha_router_key_subjects())


def test_sync_preserves_access_type():
    asyncio.run(_test_sync_preserves_access_type())
