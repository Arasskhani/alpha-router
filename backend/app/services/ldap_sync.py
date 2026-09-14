"""Sync users and groups from LDAP / Active Directory into Alpharouter.

Identity model
--------------
A directory object is matched to a local row by its **immutable** identity
(``objectGUID`` / ``entryUUID``), never by DN or sAMAccountName -- both of
those change when the object is renamed or moved between OUs, which used to
make the sync see a long-standing user as brand new, insert a duplicate, and
fail on the ``ix_users_email`` unique index. Rows written before this change
are keyed by DN, so the match falls back through DN, username, and finally
email, and rewrites ``external_id`` to the stable id whenever it matches.

Failure model
-------------
Every user is applied inside its own SAVEPOINT and flushed there, so a single
conflicting record is skipped and reported instead of rolling back the whole
run. Pruning is disabled for any run that skipped a record, because a skipped
user is exactly a user whose identity could not be confirmed.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.budget import PlanAssignment
from app.models.user import User, UserGroup, UserRoleAssignment, user_group_members
from app.services.rbac import user_has_super_admin_access
from app.services.ldap_auth import fetch_ldap_groups, fetch_ldap_users
from app.services.user_lifecycle_service import prune_sync_user, restore_directory_user
from app.services.username_norm import find_user_by_username_ci, normalize_username, username_taken_ci

logger = logging.getLogger(__name__)

# Providers whose rows the sync may claim as LDAP accounts. A SAML or OIDC row
# must never be flipped: their login path looks the user up by
# (auth_provider, external_id) and then refuses a username match on a different
# provider with 409 (see _upsert_directory_user in app/api/auth.py) -- so one
# sync run would permanently lock that person out of their own SSO.
LINKABLE_PROVIDERS = frozenset({"local", "ldap"})


class ForeignProviderAccount(Exception):
    """The matched row belongs to another identity provider; left untouched."""

    def __init__(self, user: User, matched_by: str):
        self.user = user
        self.matched_by = matched_by
        super().__init__(f"'{user.username}' belongs to {user.auth_provider}; matched by {matched_by}")


class LocalPasswordAccount(Exception):
    """A password-bearing local row matched a directory entry; not linked.

    Flipping such a row to ``ldap`` would (a) let the directory identity log in
    with the row's roles and (b) switch off its TOTP, which the login path only
    enforced for ``local`` rows. The row is left exactly as it is and the entry
    is reported in ``conflicts``; an administrator resolves it deliberately
    (rename one side, or opt in via LDAP_LINK_LOCAL_PASSWORD_ACCOUNTS).
    """

    def __init__(self, user: User, matched_by: str, reason: str):
        self.user = user
        self.matched_by = matched_by
        self.reason = reason
        super().__init__(f"'{user.username}' is a {reason}; matched by {matched_by}; not linked")


async def _is_full_administrator(db: AsyncSession, user: User) -> bool:
    if user.id is None:
        return False
    slugs = (
        (await db.execute(select(UserRoleAssignment.role_slug).where(UserRoleAssignment.user_id == user.id)))
        .scalars()
        .all()
    )
    return user_has_super_admin_access([str(s) for s in slugs])


async def _local_row_may_link(db: AsyncSession, user: User, matched_by: str) -> None:
    """Raise LocalPasswordAccount when a local row must not become an LDAP row.

    Rules (evaluated only for ``auth_provider == "local"``):
    - a row matched by its stable directory identity (GUID or historical DN)
      was created by the directory path and may always be re-linked;
    - a Full Administrator row is never linked, whatever the flag says;
    - a row that still has a local password is linked only when
      ``LDAP_LINK_LOCAL_PASSWORD_ACCOUNTS=true`` (default false);
    - a passwordless local row (provisioned ahead of the directory) links.
    """
    if matched_by in {"external_id", "dn"}:
        return
    if await _is_full_administrator(db, user):
        raise LocalPasswordAccount(user, matched_by, "Full Administrator account")
    if user.hashed_password and not get_settings().ldap_link_local_password_accounts:
        raise LocalPasswordAccount(user, matched_by, "local account with a password")


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


async def _user_with_email(
    db: AsyncSession,
    email: str,
    *,
    exclude_user_id: int | None = None,
) -> User | None:
    """Row already holding this address (``users.email`` is unique).

    Mirrors the check the admin user editor makes (``admin.py``) so the
    directory path cannot do what the admin UI is forbidden from doing.
    """
    key = email.strip().lower()
    if not key:
        return None
    stmt = select(User).where(func.lower(User.email) == key)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return (await db.execute(stmt)).scalars().first()


async def _match_directory_user(
    db: AsyncSession,
    item: dict[str, Any],
    claimed_ids: set[int],
) -> tuple[User | None, str]:
    """Find the existing row for a directory entry. Returns (user, matched_by).

    ``claimed_ids`` holds the rows already taken by an earlier entry in this
    same run. Only the email step consults it: address duplicates across two
    genuinely distinct directory objects are common, and without this guard the
    second object would adopt the first object's row and rename it on every run.
    """
    external_id = _clean(item.get("external_id"))
    dn = _clean(item.get("dn"))
    username = normalize_username(item.get("username"))
    email = _clean(item.get("email"))

    if external_id:
        found = (await db.execute(select(User).where(User.external_id == external_id))).scalars().first()
        if found:
            return found, "external_id"

    # Row stored before the GUID migration, or written by an older login path.
    if dn and dn != external_id:
        found = (await db.execute(select(User).where(User.external_id == dn))).scalars().first()
        if found:
            return found, "dn"

    if username:
        found = await find_user_by_username_ci(db, username)
        if found:
            return found, "username"

    # Last resort: the DN *and* the logon name both changed, or the row is
    # soft-deleted and still holds the address. Without this the insert below
    # would violate ix_users_email.
    if email:
        found = await _user_with_email(db, email)
        if found is not None and found.id not in claimed_ids:
            return found, "email"

    return None, ""


async def _apply_directory_profile(
    db: AsyncSession,
    user: User,
    item: dict[str, Any],
    conflicts: list[dict[str, str]],
) -> None:
    new_username = normalize_username(item.get("username"))
    if new_username and new_username != normalize_username(user.username) and not user.hashed_password:
        if not await username_taken_ci(db, new_username, exclude_user_id=user.id):
            user.username = new_username

    email = _clean(item.get("email"))
    if email and (user.email or "").strip().lower() != email.lower():
        clash = await _user_with_email(db, email, exclude_user_id=user.id)
        if clash is None:
            user.email = email
        else:
            # Two directory objects claim one address. Keep the account and its
            # current address rather than failing the run; an admin resolves it
            # in AD or in the user editor.
            conflicts.append(
                {
                    "username": user.username or new_username or "",
                    "reason": "email_in_use",
                    "detail": f"{email} already belongs to '{clash.username}'",
                }
            )
            logger.warning(
                "LDAP sync: keeping existing address for %s; %s is held by %s",
                user.username,
                email,
                clash.username,
            )

    if item.get("display_name"):
        user.display_name = item["display_name"]
    if _clean(item.get("external_id")):
        user.external_id = _clean(item.get("external_id"))
    for field in ("company", "job_title", "department", "office", "reporting_to"):
        val = item.get(field)
        if val is not None and str(val).strip():
            setattr(user, field, str(val).strip())
    user.is_active = True


async def _sync_one_user(
    db: AsyncSession,
    item: dict[str, Any],
    conflicts: list[dict[str, str]],
    claimed_ids: set[int] | None = None,
) -> tuple[User, bool, bool]:
    """Create or update one directory user. Returns (user, created, relinked)."""
    raw_username = (item.get("username") or "").strip()
    username = normalize_username(raw_username)
    existing, matched_by = await _match_directory_user(db, item, claimed_ids or set())

    if existing:
        provider = (existing.auth_provider or "local").strip().lower()
        if provider not in LINKABLE_PROVIDERS:
            # Do not restore, do not rewrite the profile, do not touch
            # external_id -- the row is owned by another provider's login flow.
            raise ForeignProviderAccount(existing, matched_by)
        was_local = provider == "local"
        if was_local:
            # Decide before touching anything: a refused row must come out of
            # the sync byte-for-byte unchanged (no restore, no profile rewrite,
            # no external_id backfill).
            await _local_row_may_link(db, existing, matched_by)
        if existing.deleted_at is not None:
            await restore_directory_user(db, existing)
        await _apply_directory_profile(db, existing, item, conflicts)
        # A local row that passed _local_row_may_link becomes the directory
        # account. ``hashed_password`` is deliberately left in place -- clearing
        # it would remove the only way back in if this row is the last
        # administrator and the directory is unreachable.
        existing.auth_provider = "ldap"
        if matched_by in {"dn", "username", "email"}:
            logger.info(
                "LDAP sync: re-linked '%s' by %s (external_id -> %s)",
                existing.username,
                matched_by,
                existing.external_id,
            )
        await db.flush()
        return existing, False, was_local

    email = _clean(item.get("email"))
    if email and await _user_with_email(db, email):
        # Unreachable via the stepped match above; kept as a guard so a future
        # change to the match order can never turn into an IntegrityError.
        conflicts.append({"username": username, "reason": "email_in_use", "detail": f"{email} already in use"})
        email = None

    user = User(
        username=username,
        auth_provider="ldap",
        email=email,
        display_name=item.get("display_name") or raw_username or username,
        external_id=_clean(item.get("external_id")),
        company=item.get("company"),
        job_title=item.get("job_title"),
        department=item.get("department"),
        office=item.get("office"),
        reporting_to=item.get("reporting_to"),
        is_active=True,
    )
    db.add(user)
    # Flush inside this user's savepoint so a constraint violation is attributed
    # to this record instead of surfacing on some later query's autoflush.
    await db.flush()
    return user, True, False


async def _sync_one_group(
    db: AsyncSession,
    item: dict[str, Any],
) -> tuple[UserGroup, bool]:
    external_id = _clean(item.get("external_id"))
    dn = _clean(item.get("dn"))

    existing = (
        (
            await db.execute(
                select(UserGroup).where(
                    UserGroup.source == "ldap",
                    UserGroup.external_id == external_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is None and dn and dn != external_id:
        existing = (
            (
                await db.execute(
                    select(UserGroup).where(
                        UserGroup.source == "ldap",
                        UserGroup.external_id == dn,
                    )
                )
            )
            .scalars()
            .first()
        )

    if existing:
        existing.name = item["name"]
        existing.description = item.get("description")
        existing.external_id = external_id
        await db.flush()
        return existing, False

    group = UserGroup(
        name=item["name"],
        description=item.get("description"),
        source="ldap",
        external_id=external_id,
    )
    db.add(group)
    await db.flush()
    return group, True


async def sync_ldap_directory(db: AsyncSession, cfg: dict) -> dict[str, Any]:
    if not cfg.get("enabled"):
        raise ValueError("LDAP is not enabled")
    if not (cfg.get("server") or "").strip():
        raise ValueError("LDAP server is required")
    if not (cfg.get("base_dn") or "").strip():
        raise ValueError("Base DN is required")

    prune = bool(cfg.get("sync_ous_prune"))
    users_data = await asyncio.to_thread(fetch_ldap_users, cfg)
    groups_data = await asyncio.to_thread(fetch_ldap_groups, cfg)

    users_new = 0
    users_updated = 0
    users_skipped = 0
    foreign_provider_skipped = 0
    local_password_skipped = 0
    local_accounts_linked = 0
    groups_new = 0
    groups_updated = 0
    groups_skipped = 0
    members_linked = 0
    users_pruned = 0
    users_soft_deleted = 0
    groups_pruned = 0

    conflicts: list[dict[str, str]] = []
    # Both identities are recorded so a row that has not been rewritten to its
    # GUID yet is still recognised as "seen" by the prune pass below.
    synced_user_keys: set[str] = set()
    synced_group_keys: set[str] = set()
    synced_usernames: set[str] = set()
    dn_by_user_id: dict[str, int] = {}
    # Rows already taken by an earlier directory entry in this run.
    claimed_ids: set[int] = set()

    for item in users_data:
        username = normalize_username(item.get("username"))
        if not username:
            continue
        synced_usernames.add(username)
        for key in (_clean(item.get("external_id")), _clean(item.get("dn"))):
            if key:
                synced_user_keys.add(key)
        try:
            async with db.begin_nested():
                user, created, relinked_local = await _sync_one_user(db, item, conflicts, claimed_ids)
        except ForeignProviderAccount as exc:
            # Deliberate, not a failure: the directory entry is understood, its
            # keys are already in synced_user_keys, and the row it collided with
            # is not an LDAP row -- so pruning stays safe and is NOT suppressed.
            foreign_provider_skipped += 1
            conflicts.append(
                {
                    "username": username,
                    "reason": "foreign_provider",
                    "detail": str(exc)[:300],
                }
            )
            logger.warning("LDAP sync: not linking '%s': %s", username, exc)
            continue
        except LocalPasswordAccount as exc:
            # Same contract as ForeignProviderAccount: deliberate skip, keys are
            # already recorded, the untouched row is 'local' so prune ignores it.
            local_password_skipped += 1
            conflicts.append(
                {
                    "username": username,
                    "reason": "local_password_account",
                    "detail": str(exc)[:300],
                }
            )
            logger.warning("LDAP sync: not linking '%s': %s", username, exc)
            continue
        except IntegrityError as exc:
            users_skipped += 1
            conflicts.append(
                {
                    "username": username,
                    "reason": "integrity_error",
                    "detail": str(getattr(exc, "orig", exc))[:300],
                }
            )
            logger.warning("LDAP sync: skipped '%s' (%s)", username, getattr(exc, "orig", exc))
            continue
        except Exception as exc:  # noqa: BLE001 - one bad record must not end the run
            users_skipped += 1
            conflicts.append({"username": username, "reason": "error", "detail": str(exc)[:300]})
            logger.exception("LDAP sync: unexpected failure for '%s'", username)
            continue

        if created:
            users_new += 1
        else:
            users_updated += 1
        if relinked_local:
            local_accounts_linked += 1
        if user.id is not None:
            claimed_ids.add(user.id)
        dn = _clean(item.get("dn"))
        if dn and user.id is not None:
            dn_by_user_id[dn] = user.id

    group_by_external: dict[str, UserGroup] = {}
    for item in groups_data:
        external_id = _clean(item.get("external_id"))
        if not external_id:
            continue
        for key in (external_id, _clean(item.get("dn"))):
            if key:
                synced_group_keys.add(key)
        try:
            async with db.begin_nested():
                group, created = await _sync_one_group(db, item)
        except Exception as exc:  # noqa: BLE001
            groups_skipped += 1
            conflicts.append({"username": item.get("name") or "", "reason": "group_error", "detail": str(exc)[:300]})
            logger.exception("LDAP sync: unexpected failure for group '%s'", item.get("name"))
            continue
        if created:
            groups_new += 1
        else:
            groups_updated += 1
        group_by_external[external_id] = group

    await db.flush()

    # Group membership is DN-valued in the directory, so the map is keyed by the
    # DN we just read -- NOT by ``external_id``, which is now a GUID.
    dn_to_user: dict[str, User] = {}
    if dn_by_user_id:
        rows = (
            (
                await db.execute(
                    select(User).where(User.id.in_(list(dn_by_user_id.values()))).options(selectinload(User.groups))
                )
            )
            .scalars()
            .all()
        )
        by_id = {u.id: u for u in rows}
        for dn, user_id in dn_by_user_id.items():
            found = by_id.get(user_id)
            if found is not None and found.deleted_at is None:
                dn_to_user[dn] = found

    for item in groups_data:
        external_id = _clean(item.get("external_id"))
        group = group_by_external.get(external_id or "")
        if not group:
            continue
        if prune:
            ldap_member_ids = {
                dn_to_user[member_dn].id for member_dn in (item.get("members") or []) if member_dn in dn_to_user
            }
            rows = (
                await db.execute(select(user_group_members.c.user_id).where(user_group_members.c.group_id == group.id))
            ).all()
            current_member_ids = [int(r[0]) for r in rows if r[0] is not None]
            stale_ids = [uid for uid in current_member_ids if uid not in ldap_member_ids]
            if stale_ids:
                await db.execute(
                    delete(user_group_members).where(
                        user_group_members.c.group_id == group.id,
                        user_group_members.c.user_id.in_(stale_ids),
                    )
                )
        for member_dn in item.get("members") or []:
            user = dn_to_user.get(member_dn)
            if not user:
                continue
            if group not in user.groups:
                user.groups.append(group)
                members_linked += 1

    # A skipped record is a record whose identity could not be confirmed, so the
    # directory snapshot is incomplete and pruning from it would delete real
    # users. Never prune from a partial run.
    prune_skipped = prune and bool(users_skipped or groups_skipped)
    prune_reason = "skipped_records" if prune_skipped else None
    ldap_directory_users: list[User] = []
    if prune and not prune_skipped:
        ldap_directory_users = (
            (await db.execute(select(User).where(User.auth_provider == "ldap", User.deleted_at.is_(None))))
            .scalars()
            .all()
        )
        # An empty directory answer, or one that would remove most of the
        # known users, is far more likely a search-base typo, a moved OU or a
        # half-failed paged search than a real mass departure. Refuse to prune
        # from it; the admin sees prune_reason in the sync result.
        if not users_data:
            prune_skipped, prune_reason = True, "empty_directory"
        elif ldap_directory_users:
            to_remove = sum(
                1
                for u in ldap_directory_users
                if not (
                    (u.external_id and u.external_id in synced_user_keys)
                    or (not u.external_id and normalize_username(u.username) in synced_usernames)
                )
            )
            ratio = to_remove / max(1, len(ldap_directory_users))
            max_ratio = float(getattr(get_settings(), "ldap_prune_max_ratio", 0.5) or 0.5)
            if to_remove >= 2 and ratio > max_ratio:
                prune_skipped, prune_reason = True, f"ratio_{ratio:.2f}_exceeds_{max_ratio:.2f}"
    if prune_skipped:
        logger.warning(
            "LDAP sync: prune suppressed (%s); %d user(s) and %d group(s) were skipped",
            prune_reason,
            users_skipped,
            groups_skipped,
        )

    if prune and not prune_skipped:
        for user in ldap_directory_users:
            if user.external_id and user.external_id in synced_user_keys:
                continue
            if not user.external_id and normalize_username(user.username) in synced_usernames:
                continue
            action = await prune_sync_user(db, user)
            if action == "soft_deleted":
                users_soft_deleted += 1
                users_pruned += 1
            elif action == "permanently_deleted":
                users_pruned += 1

        ldap_groups = (await db.execute(select(UserGroup).where(UserGroup.source == "ldap"))).scalars().all()
        for group in ldap_groups:
            if group.external_id and group.external_id in synced_group_keys:
                continue
            if await _should_prune_ldap_group(db, group):
                await _delete_ldap_group_row(db, group)
                groups_pruned += 1

    await db.commit()
    return {
        "users_synced": users_new + users_updated,
        "groups_synced": groups_new + groups_updated,
        "users_pruned": users_pruned,
        "users_soft_deleted": users_soft_deleted,
        "groups_pruned": groups_pruned,
        "members_linked": members_linked,
        "users_skipped": users_skipped,
        "groups_skipped": groups_skipped,
        "local_accounts_linked": local_accounts_linked,
        "foreign_provider_skipped": foreign_provider_skipped,
        "local_password_skipped": local_password_skipped,
        "prune_skipped": prune_skipped,
        "prune_reason": prune_reason,
        "conflicts": conflicts,
    }


async def _should_prune_ldap_group(db: AsyncSession, group: UserGroup) -> bool:
    plan = (await db.execute(select(PlanAssignment).where(PlanAssignment.group_id == group.id))).scalars().first()
    if plan:
        return False
    member_count = (
        await db.execute(select(user_group_members.c.user_id).where(user_group_members.c.group_id == group.id))
    ).all()
    if member_count:
        return False
    return True


async def _delete_ldap_group_row(db: AsyncSession, group: UserGroup) -> None:
    await db.execute(delete(PlanAssignment).where(PlanAssignment.group_id == group.id))
    await db.execute(delete(user_group_members).where(user_group_members.c.group_id == group.id))
    await db.delete(group)
