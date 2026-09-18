"""Project Advanced settings keep one row per revision number.

``update_project_config`` allocates ``revision`` as ``MAX(revision) + 1`` with no
lock, and ``project_config_versions`` had no unique constraint on
(project_id, revision) - the only MAX()+1 in the codebase with neither. Two
owners saving at the same moment both read the same maximum and both wrote it,
so a history the product calls immutable held two rows claiming one revision and
one owner's change was silently discarded.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.project import ProjectConfigVersion
from app.models.user import User
from app.services.project_config_service import update_project_config
from app.services.project_service import create_project

_POSTGRES = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


async def _owner_and_project(db: AsyncSession) -> tuple[User, str]:
    owner = User(
        username="config_owner",
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    project = await create_project(db, user=owner, name="Config")
    await db.commit()
    return owner, project["id"]


async def test_revisions_increment_one_at_a_time(db_session):
    owner, project_id = await _owner_and_project(db_session)
    for expected in (1, 2, 3):
        result = await update_project_config(
            db_session,
            project_id=project_id,
            user=owner,
            custom_prompt=f"revision {expected}",
        )
        assert result.revision == expected
    await db_session.commit()

    revisions = (
        (
            await db_session.execute(
                select(ProjectConfigVersion.revision).where(ProjectConfigVersion.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(revisions) == sorted(set(revisions)), "a revision number was reused"


@pytest.mark.skipif(not _POSTGRES, reason="needs two real transactions; set TEST_DATABASE_URL")
async def test_two_concurrent_saves_do_not_share_a_revision(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as setup:
        _owner, project_id = await _owner_and_project(setup)

    async def _save(prompt: str) -> bool:
        async with session_factory() as db:
            owner = (await db.execute(select(User).where(User.username == "config_owner"))).scalars().one()
            try:
                await update_project_config(db, project_id=project_id, user=owner, custom_prompt=prompt)
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                return False

    await asyncio.gather(_save("first"), _save("second"), return_exceptions=True)

    async with session_factory() as check:
        rows = (
            (
                await check.execute(
                    select(ProjectConfigVersion.revision).where(ProjectConfigVersion.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        distinct = int(
            (
                await check.execute(
                    select(func.count(func.distinct(ProjectConfigVersion.revision))).where(
                        ProjectConfigVersion.project_id == project_id
                    )
                )
            ).scalar_one()
        )

    assert len(rows) == distinct, f"two config versions share a revision number: {sorted(rows)}"
