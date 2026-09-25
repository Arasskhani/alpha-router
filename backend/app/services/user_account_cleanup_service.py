"""Remove all persisted data for a deleted user account."""

from __future__ import annotations

import asyncio
import datetime
import logging

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatFolder, ChatMessage, ChatSession, UserChatPrefs, UserMemory
from app.models.extension import ExtensionSession
from app.models.project import (
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    ProjectMediaAsset,
    ProjectMember,
)
from app.models.user_media_prefs import UserMediaPreferences
from app.services import object_storage_service as oss
from app.services.storage_service import user_storage_slug
from app.services.user_media_service import delete_all_user_media

logger = logging.getLogger(__name__)


async def _remaining_project_assignee_id(db: AsyncSession, project_id: str, *, exclude_user_id: int) -> int | None:
    """Pick a remaining Primary Owner, else Owner, else any remaining member."""
    for role in (PROJECT_ROLE_PRIMARY_OWNER, PROJECT_ROLE_OWNER):
        owner_id = (
            await db.execute(
                select(ProjectMember.user_id)
                .where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id != exclude_user_id,
                    ProjectMember.role == role,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if owner_id is not None:
            return int(owner_id)
    member_id = (
        await db.execute(
            select(ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id != exclude_user_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return int(member_id) if member_id is not None else None


async def _transfer_primary_owner_if_departing(db: AsyncSession, *, departing_user_id: int) -> None:
    """If the departing user is Primary Owner, promote a remaining member first.

    Demote-then-promote keeps the partial unique index (one Primary Owner).
    """
    rows = (
        (
            await db.execute(
                select(ProjectMember).where(
                    ProjectMember.user_id == departing_user_id,
                    ProjectMember.role == PROJECT_ROLE_PRIMARY_OWNER,
                )
            )
        )
        .scalars()
        .all()
    )
    for membership in rows:
        successor_id = await _remaining_project_assignee_id(
            db, membership.project_id, exclude_user_id=departing_user_id
        )
        if successor_id is None:
            continue
        successor = await db.get(ProjectMember, (membership.project_id, successor_id))
        if successor is None:
            continue
        membership.role = PROJECT_ROLE_OWNER
        await db.flush()
        successor.role = PROJECT_ROLE_PRIMARY_OWNER
        successor.updated_at = datetime.datetime.utcnow()
        await db.flush()


async def _reassign_project_chat_sessions(db: AsyncSession, user_id: int) -> int:
    sessions = (
        (
            await db.execute(
                select(ChatSession).where(
                    ChatSession.user_id == user_id,
                    ChatSession.project_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    moved = 0
    for session in sessions:
        assignee = await _remaining_project_assignee_id(db, session.project_id, exclude_user_id=user_id)
        if assignee is None:
            continue
        session.user_id = assignee
        moved += 1
    if moved:
        await db.flush()
    return moved


async def purge_user_account_data(
    db: AsyncSession,
    *,
    user_id: int,
    username: str,
) -> dict[str, int]:
    """
    Delete media rows (and referenced object-storage keys), personal chat tables,
    prefs, then sweep orphan objects under the user's CDN prefixes.

    Project-scoped chats and messages stay with the project: sessions are
    reassigned to a remaining Owner, and message authorship is SET NULL.
    """
    media_rows = await delete_all_user_media(db, user_id)

    await _transfer_primary_owner_if_departing(db, departing_user_id=user_id)

    # Project-owned files stay; drop uploader attribution (SET NULL on SQLite too).
    await db.execute(
        update(ProjectMediaAsset)
        .where(ProjectMediaAsset.uploaded_by_user_id == user_id)
        .values(uploaded_by_user_id=None)
    )

    await _reassign_project_chat_sessions(db, user_id)

    personal_session_ids = list(
        (
            await db.execute(
                select(ChatSession.id).where(
                    ChatSession.user_id == user_id,
                    ChatSession.project_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if personal_session_ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(personal_session_ids)))
        await db.execute(delete(ChatSession).where(ChatSession.id.in_(personal_session_ids)))

    await db.execute(update(ChatMessage).where(ChatMessage.user_id == user_id).values(user_id=None))

    await db.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    try:
        from app.services.user_memory_service import purge_user_memory_index

        await purge_user_memory_index(user_id)
    except Exception:
        logger.exception("Failed to purge memory vectors for user_id=%s", user_id)
    await db.execute(delete(ChatFolder).where(ChatFolder.user_id == user_id))
    # The row is emptied rather than deleted, so ON DELETE CASCADE never fires:
    # the browsers this account connected are forgotten here.
    await db.execute(delete(ExtensionSession).where(ExtensionSession.user_id == user_id))

    chat_deleted = 1

    prefs_deleted = 0
    prefs = await db.get(UserChatPrefs, user_id)
    if prefs:
        await db.delete(prefs)
        prefs_deleted = 1

    media_prefs = await db.get(UserMediaPreferences, user_id)
    if media_prefs:
        await db.delete(media_prefs)
        prefs_deleted += 1

    await db.flush()

    slug = user_storage_slug(username)
    object_storage_deleted = await asyncio.to_thread(oss.purge_user_cdn_objects, slug, user_id)
    logger.info(
        "Purged account data for user_id=%s username=%s media_rows=%s chat=%s object_storage=%s",
        user_id,
        username,
        media_rows,
        chat_deleted,
        object_storage_deleted,
    )
    return {
        "media_rows": media_rows,
        "chat_store": chat_deleted,
        "media_prefs": prefs_deleted,
        "object_storage_objects": object_storage_deleted,
    }
