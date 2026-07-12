"""Object-level authorization for media assets."""

from enum import Enum

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import MediaAsset
from app.models.user import User
from app.services.rbac import user_can_access_menu, user_can_write_menu
from app.services.user_role_service import get_user_role_slugs


class MediaAccessAction(str, Enum):
    READ = "read"
    DELETE = "delete"


def _cross_user_allowed(slugs: list[str], action: MediaAccessAction) -> bool:
    if action == MediaAccessAction.READ:
        return user_can_access_menu(slugs, "media") or user_can_access_menu(slugs, "users")
    # "media" is an end-user menu and cannot safely express scoped admin write
    # access. The users write role is the canonical cross-user deletion gate.
    return user_can_write_menu(slugs, "users")


async def load_authorized_media_asset(
    db: AsyncSession,
    actor: User,
    asset_id: int,
    *,
    action: MediaAccessAction,
    not_found_detail: str = "Media not found",
) -> MediaAsset:
    """Return an authorized asset while hiding existence from unauthorized users."""
    asset = await db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    if asset.user_id == actor.id:
        return asset

    slugs = await get_user_role_slugs(db, actor.id)
    if _cross_user_allowed(slugs, action):
        return asset
    raise HTTPException(status_code=404, detail=not_found_detail)
