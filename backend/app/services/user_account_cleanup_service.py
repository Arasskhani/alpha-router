"""Remove all persisted data for a deleted user account."""



from __future__ import annotations



import asyncio

import logging



from sqlalchemy import delete

from sqlalchemy.ext.asyncio import AsyncSession



from app.models.chat import ChatFolder, ChatMessage, ChatSession, UserChatPrefs

from app.models.user_media_prefs import UserMediaPreferences

from app.services import object_storage_service as oss

from app.services.storage_service import user_storage_slug

from app.services.user_media_service import delete_all_user_media



logger = logging.getLogger(__name__)





async def purge_user_account_data(

    db: AsyncSession,

    *,

    user_id: int,

    username: str,

) -> dict[str, int]:

    """

    Delete media rows (and referenced MinIO keys), chat tables, prefs,

    then sweep orphan objects under the user's CDN prefixes.

    """

    media_rows = await delete_all_user_media(db, user_id)



    await db.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))

    await db.execute(delete(ChatSession).where(ChatSession.user_id == user_id))

    await db.execute(delete(ChatFolder).where(ChatFolder.user_id == user_id))

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

    minio_deleted = await asyncio.to_thread(oss.purge_user_cdn_objects, slug, user_id)

    logger.info(

        "Purged account data for user_id=%s username=%s media_rows=%s chat=%s minio=%s",

        user_id,

        username,

        media_rows,

        chat_deleted,

        minio_deleted,

    )

    return {

        "media_rows": media_rows,

        "chat_store": chat_deleted,

        "media_prefs": prefs_deleted,

        "minio_objects": minio_deleted,

    }

