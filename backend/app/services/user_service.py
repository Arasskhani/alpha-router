"""User provisioning from Open WebUI / gateway identity."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.username_norm import find_user_by_username_ci, normalize_username


async def get_or_create_user_from_request(db: AsyncSession, identifier: str) -> User:
    """
    Create user on first prompt (Open WebUI passes email in `user` field).
    identifier may be email or username.
    """
    key = identifier.strip().lower()
    q = select(User).where(User.email == key)
    user = (await db.execute(q)).scalars().first()
    if not user:
        user = await find_user_by_username_ci(db, key)
    if user:
        return user
    username = normalize_username(key)
    user = User(
        username=username,
        email=key if "@" in key else f"{username}@openwebui.local",
        display_name=key,
        role="user",
        auth_provider="openwebui",
    )
    db.add(user)
    await db.flush()
    return user


async def get_user_by_api_key(db: AsyncSession, raw_key: str):
    """Resolve Alpha Router or user API key. Returns (user, source, alpha_router_key row)."""
    from app.core.security import hash_api_key
    from app.models.api_key import AlphaRouterApiKey, UserApiKey

    h = hash_api_key(raw_key)
    bk = (await db.execute(select(AlphaRouterApiKey).where(AlphaRouterApiKey.key_hash == h))).scalars().first()
    if bk:
        return None, "alpha_router_key", bk
    uk = (await db.execute(select(UserApiKey).where(UserApiKey.key_hash == h, UserApiKey.is_active == True))).scalars().first()  # noqa: E712
    if uk:
        user = await db.get(User, uk.user_id)
        return user, "user_key", None
    return None, "unknown", None
