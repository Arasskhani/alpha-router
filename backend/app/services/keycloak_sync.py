"""Keycloak user/group sync via Admin API."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User, UserGroup


async def _keycloak_admin_request(config: dict) -> tuple[httpx.AsyncClient, str, str, str] | None:
    if not config.get("enabled"):
        return None
    server = (config.get("server_url") or "").rstrip("/")
    realm = (config.get("realm") or "").strip()
    admin_id = config.get("admin_client_id") or config.get("client_id")
    admin_secret = config.get("admin_client_secret") or config.get("client_secret")
    if not server or not realm or not admin_id or not admin_secret:
        return None

    client = httpx.AsyncClient(timeout=60.0)
    token_url = f"{server}/realms/{realm}/protocol/openid-connect/token"
    tok = await client.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": admin_id,
            "client_secret": admin_secret,
        },
    )
    if tok.status_code != 200:
        await client.aclose()
        return None
    access = tok.json().get("access_token")
    if not access:
        await client.aclose()
        return None
    return client, server, realm, access


async def fetch_keycloak_groups(config: dict) -> list[dict[str, Any]]:
    ctx = await _keycloak_admin_request(config)
    if not ctx:
        return []
    client, server, realm, access = ctx
    try:
        resp = await client.get(
            f"{server}/admin/realms/{realm}/groups",
            headers={"Authorization": f"Bearer {access}"},
            params={"max": 500},
        )
        if resp.status_code != 200:
            return []
        return [
            {"name": g.get("name"), "external_id": g.get("id"), "description": g.get("path")}
            for g in resp.json()
            if g.get("name")
        ]
    finally:
        await client.aclose()


async def fetch_keycloak_users(config: dict) -> list[dict[str, Any]]:
    ctx = await _keycloak_admin_request(config)
    if not ctx:
        return []
    client, server, realm, access = ctx
    try:
        resp = await client.get(
            f"{server}/admin/realms/{realm}/users",
            headers={"Authorization": f"Bearer {access}"},
            params={"max": 500},
        )
        if resp.status_code != 200:
            return []
        out: list[dict[str, Any]] = []
        for u in resp.json():
            username = (u.get("username") or "").strip()
            if not username:
                continue
            first = (u.get("firstName") or "").strip()
            last = (u.get("lastName") or "").strip()
            display = " ".join(p for p in (first, last) if p).strip() or username
            out.append(
                {
                    "username": username,
                    "external_id": u.get("id"),
                    "email": u.get("email"),
                    "display_name": display,
                    "enabled": u.get("enabled", True),
                }
            )
        return out
    finally:
        await client.aclose()


async def fetch_keycloak_group_member_ids(config: dict, group_external_id: str) -> list[str]:
    ctx = await _keycloak_admin_request(config)
    if not ctx:
        return []
    client, server, realm, access = ctx
    try:
        resp = await client.get(
            f"{server}/admin/realms/{realm}/groups/{group_external_id}/members",
            headers={"Authorization": f"Bearer {access}"},
            params={"max": 500},
        )
        if resp.status_code != 200:
            return []
        return [str(u.get("id")) for u in resp.json() if u.get("id")]
    finally:
        await client.aclose()


def _apply_keycloak_profile(user: User, item: dict[str, Any]) -> None:
    if item.get("email"):
        user.email = item["email"]
    if item.get("display_name"):
        user.display_name = item["display_name"]
    if item.get("external_id"):
        user.external_id = item["external_id"]


async def sync_keycloak_directory(db: AsyncSession, cfg: dict) -> dict[str, int]:
    if not cfg.get("enabled"):
        raise ValueError("Keycloak is not enabled")

    users_data = await fetch_keycloak_users(cfg)
    groups_data = await fetch_keycloak_groups(cfg)

    users_new = 0
    users_updated = 0
    groups_new = 0
    groups_updated = 0
    members_linked = 0

    for item in users_data:
        username = (item.get("username") or "").strip()
        if not username:
            continue
        external_id = item.get("external_id")
        clauses = [User.username == username]
        if external_id:
            clauses.append(User.external_id == external_id)
        existing = (await db.execute(select(User).where(or_(*clauses)))).scalars().first()
        if existing:
            _apply_keycloak_profile(existing, item)
            if not (existing.auth_provider == "local" and existing.hashed_password):
                existing.auth_provider = "keycloak"
            users_updated += 1
        else:
            db.add(
                User(
                    username=username,
                    role="user",
                    auth_provider="keycloak",
                    email=item.get("email"),
                    display_name=item.get("display_name") or username,
                    external_id=external_id,
                    is_active=bool(item.get("enabled", True)),
                )
            )
            users_new += 1

    group_by_external: dict[str, UserGroup] = {}
    for item in groups_data:
        external_id = item.get("external_id")
        if not external_id:
            continue
        existing = (
            await db.execute(
                select(UserGroup).where(
                    UserGroup.source == "keycloak",
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
                source="keycloak",
                external_id=external_id,
            )
            db.add(group)
            groups_new += 1
        group_by_external[external_id] = group

    await db.flush()

    kc_users = (
        (
            await db.execute(
                select(User)
                .where(User.auth_provider == "keycloak")
                .options(selectinload(User.groups))
            )
        )
        .scalars()
        .all()
    )
    id_to_user = {u.external_id: u for u in kc_users if u.external_id}

    for item in groups_data:
        external_id = item.get("external_id") or ""
        group = group_by_external.get(external_id)
        if not group:
            continue
        member_ids = await fetch_keycloak_group_member_ids(cfg, external_id)
        for member_id in member_ids:
            user = id_to_user.get(member_id)
            if not user:
                continue
            if group not in user.groups:
                user.groups.append(group)
                members_linked += 1

    await db.commit()
    return {
        "users_synced": users_new + users_updated,
        "groups_synced": groups_new + groups_updated,
        "members_linked": members_linked,
    }
