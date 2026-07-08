"""Sync users and groups from LDAP / Active Directory into NITRO."""

import asyncio
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.budget import PlanAssignment
from app.models.user import User, UserGroup, user_group_members
from app.services.ldap_auth import fetch_ldap_groups, fetch_ldap_users
from app.services.user_lifecycle_service import prune_sync_user, restore_directory_user


async def sync_ldap_directory(db: AsyncSession, cfg: dict) -> dict[str, int]:
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
    groups_new = 0
    groups_updated = 0
    members_linked = 0
    users_pruned = 0
    users_soft_deleted = 0
    groups_pruned = 0

    synced_user_external: set[str] = set()
    synced_group_external: set[str] = set()

    for item in users_data:
        username = (item.get("username") or "").strip()
        if not username:
            continue
        external_id = item.get("external_id")
        if external_id:
            synced_user_external.add(external_id)
        existing = None
        if external_id:
            existing = (
                await db.execute(select(User).where(User.external_id == external_id))
            ).scalars().first()
        if not existing:
            existing = (await db.execute(select(User).where(User.username == username))).scalars().first()

        if existing:
            if existing.deleted_at is not None:
                await restore_directory_user(db, existing)
            await _apply_directory_profile(db, existing, item)
            if not (existing.auth_provider == "local" and existing.hashed_password):
                existing.auth_provider = "ldap"
            users_updated += 1
        else:
            user = User(
                username=username,
                role="user",
                auth_provider="ldap",
                email=item.get("email"),
                display_name=item.get("display_name") or username,
                external_id=external_id,
                job_title=item.get("job_title"),
                department=item.get("department"),
                office=item.get("office"),
                reporting_to=item.get("reporting_to"),
                is_active=True,
            )
            db.add(user)
            users_new += 1

    group_by_external: dict[str, UserGroup] = {}
    for item in groups_data:
        external_id = item.get("external_id")
        if not external_id:
            continue
        synced_group_external.add(external_id)
        existing = (
            await db.execute(
                select(UserGroup).where(
                    UserGroup.source == "ldap",
                    UserGroup.external_id == external_id,
                )
            )
        ).scalars().first()
        if existing:
            existing.name = item["name"]
            existing.description = item.get("description")
            group = existing
            groups_updated += 1
        else:
            group = UserGroup(
                name=item["name"],
                description=item.get("description"),
                source="ldap",
                external_id=external_id,
            )
            db.add(group)
            groups_new += 1
        group_by_external[external_id] = group

    await db.flush()

    ldap_users = (
        (
            await db.execute(
                select(User)
                .where(User.auth_provider == "ldap", User.deleted_at.is_(None))
                .options(selectinload(User.groups))
            )
        )
        .scalars()
        .all()
    )
    dn_to_user = {u.external_id: u for u in ldap_users if u.external_id}

    for item in groups_data:
        external_id = item.get("external_id")
        group = group_by_external.get(external_id or "")
        if not group:
            continue
        if prune:
            ldap_member_ids = {
                dn_to_user[member_dn].id
                for member_dn in (item.get("members") or [])
                if member_dn in dn_to_user
            }
            rows = (
                await db.execute(
                    select(user_group_members.c.user_id).where(
                        user_group_members.c.group_id == group.id
                    )
                )
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

    if prune:
        ldap_directory_users = (
            await db.execute(
                select(User).where(User.auth_provider == "ldap", User.deleted_at.is_(None))
            )
        ).scalars().all()
        for user in ldap_directory_users:
            if user.external_id and user.external_id in synced_user_external:
                continue
            if not user.external_id and user.username in {
                (x.get("username") or "").strip() for x in users_data
            }:
                continue
            action = await prune_sync_user(db, user)
            if action == "soft_deleted":
                users_soft_deleted += 1
                users_pruned += 1
            elif action == "permanently_deleted":
                users_pruned += 1

        ldap_groups = (
            await db.execute(select(UserGroup).where(UserGroup.source == "ldap"))
        ).scalars().all()
        for group in ldap_groups:
            if group.external_id and group.external_id in synced_group_external:
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
    }


async def _should_prune_ldap_group(db: AsyncSession, group: UserGroup) -> bool:
    plan = (
        await db.execute(select(PlanAssignment).where(PlanAssignment.group_id == group.id))
    ).scalars().first()
    if plan:
        return False
    member_count = (
        await db.execute(
            select(user_group_members.c.user_id).where(user_group_members.c.group_id == group.id)
        )
    ).all()
    if member_count:
        return False
    return True


async def _delete_ldap_group_row(db: AsyncSession, group: UserGroup) -> None:
    await db.execute(delete(PlanAssignment).where(PlanAssignment.group_id == group.id))
    await db.execute(delete(user_group_members).where(user_group_members.c.group_id == group.id))
    await db.delete(group)


async def _apply_directory_profile(db: AsyncSession, user: User, item: dict[str, Any]) -> None:
    new_username = (item.get("username") or "").strip()
    if (
        new_username
        and new_username != user.username
        and not user.hashed_password
    ):
        conflict = (
            await db.execute(
                select(User).where(User.username == new_username, User.id != user.id)
            )
        ).scalars().first()
        if not conflict:
            user.username = new_username
    if item.get("email"):
        user.email = item["email"]
    if item.get("display_name"):
        user.display_name = item["display_name"]
    if item.get("external_id"):
        user.external_id = item["external_id"]
    for field in ("job_title", "department", "office", "reporting_to"):
        val = item.get(field)
        if val is not None and str(val).strip():
            setattr(user, field, str(val).strip())
    user.is_active = True
