"""Load and persist multiple RBAC role assignments per user."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRoleAssignment
from app.services.rbac import (
    FULL_ADMIN_SLUG,
    LEGACY_ADMIN_SLUG,
    SUPER_ADMIN_SLUG,
    USER_SLUG,
    bootstrap_super_admin_role_slugs,
    is_assignable_role_slug,
    normalize_role_slug,
    primary_role_slug,
    user_has_super_admin_access,
)


async def get_user_role_slugs(db: AsyncSession, user_id: int) -> list[str]:
    rows = (
        await db.execute(
            select(UserRoleAssignment.role_slug)
            .where(UserRoleAssignment.user_id == user_id)
            .order_by(UserRoleAssignment.role_slug)
        )
    ).scalars().all()
    if rows:
        return _normalize_role_list([str(r) for r in rows])
    user = await db.get(User, user_id)
    if user and user.role:
        return _normalize_role_list([user.role])
    return [USER_SLUG]


async def get_roles_map(db: AsyncSession, user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(UserRoleAssignment.user_id, UserRoleAssignment.role_slug)
            .where(UserRoleAssignment.user_id.in_(user_ids))
            .order_by(UserRoleAssignment.user_id, UserRoleAssignment.role_slug)
        )
    ).all()
    out: dict[int, list[str]] = {uid: [] for uid in user_ids}
    for uid, slug in rows:
        if uid is not None:
            out.setdefault(int(uid), []).append(normalize_role_slug(str(slug)))
    for uid in user_ids:
        if not out.get(uid):
            user = await db.get(User, uid)
            out[uid] = [normalize_role_slug(user.role if user else USER_SLUG)]
    return out


def _normalize_role_list(slugs: list[str] | None) -> list[str]:
    if not slugs:
        return [USER_SLUG]
    seen: set[str] = set()
    out: list[str] = []
    for raw in slugs:
        slug = normalize_role_slug(raw)
        if not is_assignable_role_slug(slug):
            continue
        if slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out or [USER_SLUG]


async def set_user_roles(db: AsyncSession, user: User, slugs: list[str] | None) -> list[str]:
    normalized = _normalize_role_list(slugs)
    await db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id))
    for slug in normalized:
        db.add(UserRoleAssignment(user_id=user.id, role_slug=slug))
    user.role = primary_role_slug(normalized)
    await db.flush()
    return normalized


async def user_has_full_administrator(db: AsyncSession, user_id: int) -> bool:
    slugs = await get_user_role_slugs(db, user_id)
    return user_has_super_admin_access(slugs)


async def count_full_administrators(db: AsyncSession) -> int:
    user_ids = (await db.execute(select(User.id))).scalars().all()
    total = 0
    for uid in user_ids:
        if uid is not None and await user_has_full_administrator(db, int(uid)):
            total += 1
    return total


async def count_active_full_administrators(db: AsyncSession) -> int:
    user_ids = (
        await db.execute(select(User.id).where(User.is_active.is_(True)))
    ).scalars().all()
    total = 0
    for uid in user_ids:
        if uid is not None and await user_has_full_administrator(db, int(uid)):
            total += 1
    return total


async def ensure_super_admin_roles(db: AsyncSession, user: User, *, admin_username: str) -> None:
    """Ensure bootstrap / legacy global admin accounts hold the Super Admin role."""
    slugs = await get_user_role_slugs(db, user.id)
    normalized = {normalize_role_slug(s) for s in slugs}

    if user_has_super_admin_access(slugs):
        if normalized == {SUPER_ADMIN_SLUG}:
            return
        if FULL_ADMIN_SLUG in normalized or LEGACY_ADMIN_SLUG in normalized:
            await set_user_roles(db, user, bootstrap_super_admin_role_slugs())
        return

    legacy_global = normalize_role_slug(user.role) in (FULL_ADMIN_SLUG, LEGACY_ADMIN_SLUG)
    if legacy_global or user.username == admin_username:
        await set_user_roles(db, user, bootstrap_super_admin_role_slugs())
