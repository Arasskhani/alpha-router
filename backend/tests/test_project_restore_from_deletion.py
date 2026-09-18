"""A project marked for deletion can be taken back, as the page says it can.

Projects.tsx tells the owner: "These projects are marked for deletion. Owners
can restore them or purge now." ``restore_project`` answered
``Cannot restore a project that is pending deletion``, and nothing anywhere in
the codebase moved a project off that status - the only write to it was the one
that set it. The 30-day grace period existed and could not be used.
"""

from __future__ import annotations

import pytest

from app.core.security import hash_password
from app.models.project import (
    PROJECT_STATUS_ACTIVE,
    PROJECT_STATUS_ARCHIVED,
    PROJECT_STATUS_DELETION_PENDING,
    Project,
)
from app.models.user import User
from app.services.project_service import (
    archive_project,
    create_project,
    delete_project,
    restore_project,
)


async def _owned_project(db_session, username: str) -> tuple[User, str]:
    owner = User(
        username=username,
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(owner)
    await db_session.flush()
    project = await create_project(db_session, user=owner, name="Recoverable")
    await db_session.flush()
    return owner, project["id"]


async def test_a_deleted_project_comes_back_active(db_session):
    owner, project_id = await _owned_project(db_session, "restorer")
    await delete_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()
    assert (await db_session.get(Project, project_id)).status == PROJECT_STATUS_DELETION_PENDING

    result = await restore_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()

    assert result is not None
    assert (await db_session.get(Project, project_id)).status == PROJECT_STATUS_ACTIVE


async def test_a_project_archived_before_deletion_comes_back_archived(db_session):
    """Restoring must not quietly republish it to Explore."""

    owner, project_id = await _owned_project(db_session, "archiver")
    await archive_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()
    await delete_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()

    await restore_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()

    assert (await db_session.get(Project, project_id)).status == PROJECT_STATUS_ARCHIVED


async def test_restoring_an_archived_project_still_activates_it(db_session):
    owner, project_id = await _owned_project(db_session, "unarchiver")
    await archive_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()

    await restore_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()

    project = await db_session.get(Project, project_id)
    assert project.status == PROJECT_STATUS_ACTIVE
    assert project.archived_at is None


async def test_a_non_owner_cannot_restore(db_session):
    from fastapi import HTTPException

    owner, project_id = await _owned_project(db_session, "real_owner")
    await delete_project(db_session, project_id=project_id, user=owner)
    await db_session.flush()

    stranger = User(
        username="passer_by",
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.flush()

    # A stranger is told the project does not exist rather than that they may
    # not touch it, which is the right answer for a private project.
    with pytest.raises(HTTPException) as exc:
        await restore_project(db_session, project_id=project_id, user=stranger)
    assert exc.value.status_code in (403, 404)
    assert (await db_session.get(Project, project_id)).status == PROJECT_STATUS_DELETION_PENDING
