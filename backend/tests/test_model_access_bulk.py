"""Bulk access: the last change is the source of truth.

Bulk edit could set a model's access *type* and nothing else. An administrator
could privatise forty models and then had no way to say who they were private
to except opening each one; and because the old path left each model's existing
assignments alone, one action could leave the selected models with different
audiences depending on what they already had.

These cover the two pieces that fix it: a summary of the audience a selection
currently has (including the partial case), and an apply that writes exactly
what it was given to every selected model.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel, ModelAccessAssignment
from app.models.user import User, UserGroup
from app.services.model_access_service import (
    ACCESS_PRIVATE,
    ACCESS_PUBLIC,
    bulk_set_model_access,
    set_model_access,
    summarize_access_for_models,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession, username: str) -> User:
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _group(db: AsyncSession, name: str) -> UserGroup:
    g = UserGroup(name=name, source="local")
    db.add(g)
    await db.flush()
    return g


async def _models(db: AsyncSession, count: int) -> list[AIModel]:
    conn = Connection(name="or", provider_type="openrouter", api_key_encrypted="enc", is_active=True)
    db.add(conn)
    await db.flush()
    rows = []
    for i in range(count):
        m = AIModel(
            connection_id=conn.id,
            external_id=f"vendor/model-{i}",
            display_name=f"model {i}",
            provider_type="openrouter",
            is_enabled=True,
            access_type=ACCESS_PUBLIC,
        )
        db.add(m)
        rows.append(m)
    await db.flush()
    return rows


async def _assignments(db: AsyncSession, model_id: int) -> tuple[set[int], set[int]]:
    rows = (
        (await db.execute(select(ModelAccessAssignment).where(ModelAccessAssignment.model_id == model_id)))
        .scalars()
        .all()
    )
    return (
        {int(r.user_id) for r in rows if r.user_id is not None},
        {int(r.group_id) for r in rows if r.group_id is not None},
    )


class TestSummary:
    async def test_it_reports_who_holds_access_and_on_how_many(self, db):
        models = await _models(db, 3)
        eng = await _group(db, "engineering")
        fin = await _group(db, "finance")
        for m in models:
            await set_model_access(db, m, access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        # Finance only has one of the three — the partial case an administrator
        # must see before replacing the audience.
        await set_model_access(db, models[0], access_type=ACCESS_PRIVATE, group_ids=[eng.id, fin.id])
        await db.commit()

        summary = await summarize_access_for_models(db, [m.id for m in models])

        assert summary["model_count"] == 3
        assert summary["private_count"] == 3
        by_name = {g["name"]: g for g in summary["groups"]}
        assert by_name["engineering"]["model_count"] == 3
        assert by_name["finance"]["model_count"] == 1

    async def test_users_and_groups_come_back_named(self, db):
        models = await _models(db, 1)
        alice = await _user(db, "alice")
        eng = await _group(db, "engineering")
        await set_model_access(db, models[0], access_type=ACCESS_PRIVATE, user_ids=[alice.id], group_ids=[eng.id])
        await db.commit()

        summary = await summarize_access_for_models(db, [models[0].id])
        assert [u["username"] for u in summary["users"]] == ["alice"]
        assert [g["name"] for g in summary["groups"]] == ["engineering"]

    async def test_an_empty_selection_is_not_an_error(self, db):
        assert (await summarize_access_for_models(db, []))["model_count"] == 0


class TestApply:
    async def test_the_submitted_audience_replaces_whatever_was_there(self, db):
        """The example this was built for: private to engineering and finance,
        submitted with engineering alone, ends up private to engineering."""
        models = await _models(db, 2)
        eng = await _group(db, "engineering")
        fin = await _group(db, "finance")
        for m in models:
            await set_model_access(db, m, access_type=ACCESS_PRIVATE, group_ids=[eng.id, fin.id])
        await db.commit()

        await bulk_set_model_access(db, [m.id for m in models], access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        await db.commit()

        for m in models:
            users, groups = await _assignments(db, m.id)
            assert groups == {eng.id}
            assert users == set()

    async def test_every_selected_model_ends_up_identical(self, db):
        """One action, one outcome — not one that depends on prior state."""
        models = await _models(db, 3)
        eng = await _group(db, "engineering")
        alice = await _user(db, "alice")
        # Start them deliberately inconsistent.
        await set_model_access(db, models[0], access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        await set_model_access(db, models[1], access_type=ACCESS_PUBLIC)
        await db.commit()

        await bulk_set_model_access(
            db,
            [m.id for m in models],
            access_type=ACCESS_PRIVATE,
            user_ids=[alice.id],
            group_ids=[eng.id],
        )
        await db.commit()

        for m in models:
            await db.refresh(m)
            assert m.access_type == ACCESS_PRIVATE
            users, groups = await _assignments(db, m.id)
            assert users == {alice.id}
            assert groups == {eng.id}

    async def test_applying_twice_changes_nothing_the_second_time(self, db):
        models = await _models(db, 2)
        eng = await _group(db, "engineering")
        ids = [m.id for m in models]

        await bulk_set_model_access(db, ids, access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        await db.commit()
        first = [await _assignments(db, m.id) for m in models]

        await bulk_set_model_access(db, ids, access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        await db.commit()
        assert [await _assignments(db, m.id) for m in models] == first

    async def test_an_empty_audience_means_administrators_only(self, db):
        models = await _models(db, 2)
        eng = await _group(db, "engineering")
        for m in models:
            await set_model_access(db, m, access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        await db.commit()

        result = await bulk_set_model_access(db, [m.id for m in models], access_type=ACCESS_PRIVATE)
        await db.commit()

        assert result["users"] == 0 and result["groups"] == 0
        for m in models:
            await db.refresh(m)
            assert m.access_type == ACCESS_PRIVATE
            assert await _assignments(db, m.id) == (set(), set())

    async def test_going_public_clears_the_audience(self, db):
        models = await _models(db, 2)
        eng = await _group(db, "engineering")
        for m in models:
            await set_model_access(db, m, access_type=ACCESS_PRIVATE, group_ids=[eng.id])
        await db.commit()

        await bulk_set_model_access(db, [m.id for m in models], access_type=ACCESS_PUBLIC, group_ids=[eng.id])
        await db.commit()

        for m in models:
            await db.refresh(m)
            assert m.access_type == ACCESS_PUBLIC
            assert await _assignments(db, m.id) == (set(), set())

    async def test_a_deleted_user_is_not_assigned(self, db):
        models = await _models(db, 1)
        ghost = await _user(db, "ghost")
        await db.commit()
        missing_id = ghost.id + 5000

        result = await bulk_set_model_access(
            db, [models[0].id], access_type=ACCESS_PRIVATE, user_ids=[ghost.id, missing_id]
        )
        await db.commit()
        assert result["users"] == 1
        users, _groups = await _assignments(db, models[0].id)
        assert users == {ghost.id}

    async def test_a_bad_access_type_is_refused(self, db):
        models = await _models(db, 1)
        await db.commit()
        with pytest.raises(ValueError):
            await bulk_set_model_access(db, [models[0].id], access_type="secret")

    async def test_no_models_is_a_no_op(self, db):
        assert await bulk_set_model_access(db, [], access_type=ACCESS_PRIVATE) == {
            "models": 0,
            "users": 0,
            "groups": 0,
        }


def test_the_access_change_is_audited():
    """A permission change has to leave a record; neither path did."""
    import inspect

    from app.api import admin

    source = inspect.getsource(admin)
    assert 'action="model_access_changed"' in source
    # Single model, bulk private, and bulk public all leave a record.
    assert source.count("await _audit_model_access(") == 3


async def test_an_id_that_is_not_a_model_writes_nothing(db):
    """The UPDATE would skip it; the INSERT would have written an orphan row."""
    models = await _models(db, 1)
    eng = await _group(db, "engineering")
    await db.commit()
    ghost_id = models[0].id + 9999

    result = await bulk_set_model_access(db, [models[0].id, ghost_id], access_type=ACCESS_PRIVATE, group_ids=[eng.id])
    await db.commit()

    assert result["models"] == 1
    orphans = (
        (await db.execute(select(ModelAccessAssignment).where(ModelAccessAssignment.model_id == ghost_id)))
        .scalars()
        .all()
    )
    assert orphans == []
