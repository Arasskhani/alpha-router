"""Load and persist multiple RBAC role assignments per user."""

from __future__ import annotations

from sqlalchemy import delete, false, or_, select
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
    """Return assignable role slugs from ``user_role_assignments`` only.

    Users with no assignment rows are treated as the end-user role.
    """
    rows = (
        (
            await db.execute(
                select(UserRoleAssignment.role_slug)
                .where(UserRoleAssignment.user_id == user_id)
                .order_by(UserRoleAssignment.role_slug)
            )
        )
        .scalars()
        .all()
    )
    if rows:
        return _normalize_role_list([str(r) for r in rows])
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
    raw: dict[int, list[str]] = {uid: [] for uid in user_ids}
    for uid, slug in rows:
        if uid is not None:
            raw.setdefault(int(uid), []).append(str(slug))
    return {uid: _normalize_role_list(slugs) for uid, slugs in raw.items()}


async def primary_role_for_user(db: AsyncSession, user_id: int) -> str:
    """Derived display/JWT primary slug from assignment rows."""
    return primary_role_slug(await get_user_role_slugs(db, user_id))


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
    """Replace the user's role assignments. Assignments are the sole source of truth."""
    normalized = _normalize_role_list(slugs)
    await db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id))
    for slug in normalized:
        db.add(UserRoleAssignment(user_id=user.id, role_slug=slug))
    await db.flush()
    return normalized


async def user_has_full_administrator(db: AsyncSession, user_id: int) -> bool:
    slugs = await get_user_role_slugs(db, user_id)
    return user_has_super_admin_access(slugs)


async def user_bypasses_maker_checker(db: AsyncSession, user_id: int) -> bool:
    """Super Admin may complete both maker and checker steps (break-glass)."""

    return await user_has_full_administrator(db, user_id)


async def count_active_full_administrators(db: AsyncSession) -> int:
    """How many Full Administrators could actually sign in right now.

    Every guard that protects the organisation from locking itself out has to
    ask this question, and only this one. A count that includes disabled or
    soft-deleted accounts reports administrators who cannot log in: with two
    Super Admins, soft-deleting one and then permanently deleting the other was
    allowed, because the count still read 2.

    One query, not one per user: the guard runs on the deletion path, where an
    installation with a synced directory would otherwise pay a full table walk.
    """

    rows = (
        await db.execute(
            select(UserRoleAssignment.user_id, UserRoleAssignment.role_slug)
            .join(User, User.id == UserRoleAssignment.user_id)
            .where(User.is_active.is_(True), User.deleted_at.is_(None))
        )
    ).all()
    by_user: dict[int, list[str]] = {}
    for user_id, slug in rows:
        if user_id is not None:
            by_user.setdefault(int(user_id), []).append(slug)
    return sum(1 for slugs in by_user.values() if user_has_super_admin_access(slugs))


async def ensure_bootstrap_admin_roles(db: AsyncSession, *, admin_username: str) -> int:
    """Run ``ensure_super_admin_roles`` over the accounts it can actually change.

    Startup used to run it over every user, in every uvicorn worker: one query
    for that user's role assignments, per user, per worker. Nothing in
    ``ensure_super_admin_roles`` can change an account that is neither the
    bootstrap one nor carrying a legacy admin slug, so those two are the whole
    candidate set - a handful of rows on any installation.

    Returns the number of accounts examined.
    """

    legacy = {FULL_ADMIN_SLUG, LEGACY_ADMIN_SLUG}
    # Normalisation happens in Python, so match on the raw slugs that normalise
    # to a legacy one rather than guessing at their spelling in SQL. The
    # distinct set is tiny - one row per role in use.
    stored_slugs = (await db.execute(select(UserRoleAssignment.role_slug).distinct())).scalars().all()
    legacy_slugs = [slug for slug in stored_slugs if normalize_role_slug(slug) in legacy]

    holds_legacy_slug = (
        User.id.in_(select(UserRoleAssignment.user_id).where(UserRoleAssignment.role_slug.in_(legacy_slugs)))
        if legacy_slugs
        else false()
    )
    candidates = (
        (await db.execute(select(User).where(or_(User.username == admin_username, holds_legacy_slug)))).scalars().all()
    )
    for candidate in candidates:
        await ensure_super_admin_roles(db, candidate, admin_username=admin_username)
    return len(candidates)


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

    if user.username == admin_username:
        await set_user_roles(db, user, bootstrap_super_admin_role_slugs())
