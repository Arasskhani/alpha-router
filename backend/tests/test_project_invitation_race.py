"""A single-use invitation admits one person, even under a race.

``claim_invitation`` read ``use_count``, compared it to ``max_uses`` in Python,
and wrote back ``use_count + 1``. ``project_members`` is keyed on
(project, user), so two *different* people claiming the same link concurrently
never collided on insert: both read 0, both passed the check, both wrote 1. A
link marked as used once had admitted two members - an authorization bypass, not
a counter drift.

The sequential case was already covered and always passed, which is why this
went unnoticed. The concurrent case needs two real transactions, so it runs only
against PostgreSQL.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.project import ProjectMember
from app.models.user import User
from app.services.project_service import (
    ProjectValidationError,
    claim_invitation,
    create_invitation,
    create_project,
)

_POSTGRES = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


async def _person(db: AsyncSession, username: str) -> User:
    row = User(
        username=username,
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _single_use_link(db: AsyncSession) -> tuple[str, str]:
    owner = await _person(db, "invite_owner")
    project = await create_project(db, user=owner, name="Race")
    invitation = await create_invitation(
        db,
        project_id=project["id"],
        user=owner,
        role="viewer",
        max_uses=1,
    )
    await db.commit()
    return project["id"], invitation["token"]


async def test_a_second_sequential_claim_is_refused(db_session):
    project_id, token = await _single_use_link(db_session)
    first = await _person(db_session, "claimer_one")
    second = await _person(db_session, "claimer_two")
    await db_session.commit()

    assert await claim_invitation(db_session, token=token, user=first) is not None
    with pytest.raises(ProjectValidationError, match="exhausted"):
        await claim_invitation(db_session, token=token, user=second)


@pytest.mark.skipif(not _POSTGRES, reason="needs two real transactions; set TEST_DATABASE_URL")
async def test_two_people_cannot_claim_the_same_single_use_link(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as setup:
        project_id, token = await _single_use_link(setup)
        await _person(setup, "racer_one")
        await _person(setup, "racer_two")
        await setup.commit()

    async def _claim(username: str) -> bool:
        async with session_factory() as db:
            person = (await db.execute(select(User).where(User.username == username))).scalars().one()
            try:
                await claim_invitation(db, token=token, user=person)
                await db.commit()
                return True
            except ProjectValidationError:
                await db.rollback()
                return False

    results = await asyncio.gather(_claim("racer_one"), _claim("racer_two"), return_exceptions=True)
    succeeded = [r for r in results if r is True]

    async with session_factory() as check:
        members = int(
            (
                await check.execute(
                    select(func.count()).select_from(ProjectMember).where(ProjectMember.project_id == project_id)
                )
            ).scalar_one()
        )

    assert len(succeeded) == 1, f"both claims succeeded: {results}"
    # The owner plus exactly one invitee.
    assert members == 2, f"a single-use invitation admitted {members - 1} people"
