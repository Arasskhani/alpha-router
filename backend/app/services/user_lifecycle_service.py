"""Soft delete, restore, and permanent removal of user accounts."""

from __future__ import annotations

import datetime

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import PlanAssignment
from app.models.logging import RequestLog
from app.models.user import User, user_group_members
from app.services.user_account_cleanup_service import purge_user_account_data
from app.services.user_role_service import user_has_full_administrator, count_full_administrators


async def record_user_login(db: AsyncSession, user: User) -> None:
    user.last_login_at = datetime.datetime.utcnow()
    await db.flush()


async def soft_delete_user(db: AsyncSession, user: User) -> None:
    user.deleted_at = datetime.datetime.utcnow()
    user.is_active = False
    await db.execute(delete(user_group_members).where(user_group_members.c.user_id == user.id))


async def restore_directory_user(db: AsyncSession, user: User) -> None:
    user.deleted_at = None
    user.is_active = True


async def permanently_delete_user(db: AsyncSession, user: User) -> None:
    if await user_has_full_administrator(db, user.id):
        if await count_full_administrators(db) <= 1:
            raise ValueError("Cannot delete the last Full Administrator account")
    from app.models.api_key import UserApiKey

    user_id = user.id
    username = user.username
    await purge_user_account_data(db, user_id=user_id, username=username)
    await db.execute(update(RequestLog).where(RequestLog.user_id == user_id).values(user_id=None))
    await db.execute(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await db.execute(delete(PlanAssignment).where(PlanAssignment.user_id == user_id))
    await db.execute(delete(user_group_members).where(user_group_members.c.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))


async def prune_sync_user(db: AsyncSession, user: User) -> str:
    """Move LDAP users outside the OU filter to Deleted Users (preserve data)."""
    if await user_has_full_administrator(db, user.id):
        return "skipped"
    if user.deleted_at is not None:
        return "skipped"
    await soft_delete_user(db, user)
    return "soft_deleted"
