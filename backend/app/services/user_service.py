"""User provisioning from Open WebUI / gateway identity."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import API_KEY_PREFIX
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
        auth_provider="openwebui",
    )
    db.add(user)
    await db.flush()
    return user


async def get_user_by_api_key(db: AsyncSession, raw_key: str):
    """Resolve a gateway or personal API key.

    Returns (user, source, router_key, user_api_key).
    """
    from app.core.security import hash_api_key
    from app.models.api_key import AlphaRouterApiKey, UserApiKey

    if not raw_key.startswith(API_KEY_PREFIX):
        return None, "unknown", None, None

    h = hash_api_key(raw_key)
    router_key = (
        await db.execute(
            select(AlphaRouterApiKey).where(AlphaRouterApiKey.key_hash == h)
        )
    ).scalars().first()
    if router_key:
        return None, "alpha_router_key", router_key, None
    uk = (await db.execute(select(UserApiKey).where(UserApiKey.key_hash == h, UserApiKey.is_active == True))).scalars().first()  # noqa: E712
    if uk:
        user = await db.get(User, uk.user_id)
        return user, "user_key", None, uk
    return None, "unknown", None, None
