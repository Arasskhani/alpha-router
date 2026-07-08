"""Admin UI: configure LDAP and Keycloak."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_authentication, require_authentication_write
from app.database import get_db
from app.models.auth_provider import AuthProviderConfig
from app.models.user import User
from app.services.auth_config import get_provider_config, save_provider_config
from app.services.ldap_auth import test_ldap_connection
from app.services.ldap_config import (
    merge_simple_ldap_config,
    parse_sync_ous,
    resolve_password,
    simple_public_view,
)
from app.services.ldap_sync import sync_ldap_directory
from app.services.auth_sync_scheduler import refresh_auth_sync_schedules
from app.services.keycloak_sync import fetch_keycloak_groups, sync_keycloak_directory

router = APIRouter(prefix="/api/admin/authentication", tags=["authentication"])


class LdapSimpleIn(BaseModel):
    enabled: bool = False
    dc_host: str = ""
    bind_username: str = ""
    bind_password: str = ""
    port: int = Field(default=389, ge=1, le=65535)
    use_ssl: bool = False
    trust_untrusted_cert: bool = False
    sync_ous: str = ""
    sync_ous_prune: bool = False
    sync_schedule_enabled: bool = False
    sync_schedule_hour: int = Field(default=3, ge=0, le=23)
    sync_schedule_minute: int = Field(default=0, ge=0, le=59)


class KeycloakConfigIn(BaseModel):
    enabled: bool = False
    server_url: str = ""
    realm: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8080/api/auth/keycloak/callback"
    admin_client_id: str = ""
    admin_client_secret: str = ""
    sync_schedule_enabled: bool = False
    sync_schedule_hour: int = Field(default=3, ge=0, le=23)
    sync_schedule_minute: int = Field(default=0, ge=0, le=59)


@router.get("/ldap")
async def get_ldap(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    row = await db.get(AuthProviderConfig, "ldap")
    if row and row.config_json:
        raw = {"enabled": row.enabled, **json.loads(row.config_json)}
    else:
        raw = await get_provider_config(db, "ldap")
    return simple_public_view(raw)


@router.put("/ldap")
async def save_ldap(body: LdapSimpleIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)):
    existing_row = await db.get(AuthProviderConfig, "ldap")
    existing: dict = {}
    if existing_row and existing_row.config_json:
        existing = json.loads(existing_row.config_json)

    password = resolve_password(body.bind_password, existing)
    ous = parse_sync_ous(body.sync_ous)
    if not password and not existing.get("bind_password"):
        raise HTTPException(400, "Password is required")

    try:
        data = merge_simple_ldap_config(
            body.enabled,
            body.dc_host,
            body.bind_username,
            password,
            body.port,
            use_ssl=body.use_ssl,
            trust_untrusted_cert=body.trust_untrusted_cert,
            sync_ous=ous,
            sync_ous_prune=body.sync_ous_prune,
            existing=existing,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    data["sync_schedule_enabled"] = body.sync_schedule_enabled
    data["sync_schedule_hour"] = body.sync_schedule_hour
    data["sync_schedule_minute"] = body.sync_schedule_minute

    await save_provider_config(db, "ldap", body.enabled, data)
    await refresh_auth_sync_schedules()
    return {"ok": True, **simple_public_view(data)}


@router.post("/ldap/sync")
async def sync_ldap_ad(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)):
    cfg = await get_provider_config(db, "ldap")
    if not cfg.get("enabled"):
        raise HTTPException(400, "LDAP is not enabled")
    try:
        return await sync_ldap_directory(db, cfg)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"LDAP sync failed: {e}") from e


@router.post("/ldap/test")
async def test_ldap(
    body: LdapSimpleIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_authentication_write),
):
    """Bind with the service account and run a small LDAP query."""
    existing_row = await db.get(AuthProviderConfig, "ldap")
    existing: dict = {}
    if existing_row and existing_row.config_json:
        existing = json.loads(existing_row.config_json)

    password = resolve_password(body.bind_password, existing)
    ous = parse_sync_ous(body.sync_ous)
    if not password and not existing.get("bind_password"):
        raise HTTPException(400, "Password is required")

    try:
        cfg = merge_simple_ldap_config(
            body.enabled,
            body.dc_host,
            body.bind_username,
            password,
            body.port,
            use_ssl=body.use_ssl,
            trust_untrusted_cert=body.trust_untrusted_cert,
            sync_ous=ous,
            sync_ous_prune=body.sync_ous_prune,
            existing=existing,
        )
    except ValueError as exc:
        raise HTTPException(400, f"Failed: {exc}") from exc

    cfg["enabled"] = True
    try:
        result = await asyncio.to_thread(test_ldap_connection, cfg)
    except Exception as exc:
        raise HTTPException(400, f"Failed: {exc}") from exc

    return {
        "ok": True,
        "status": "Success",
        "port": result.get("port"),
        "use_ssl": result.get("use_ssl"),
        "encryption": result.get("encryption"),
    }


@router.get("/keycloak")
async def get_keycloak(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    cfg = await get_provider_config(db, "keycloak")
    safe = {**cfg}
    for key in ("client_secret", "admin_client_secret"):
        if safe.get(key):
            safe[key] = "********"
    return safe


@router.put("/keycloak")
async def save_keycloak(body: KeycloakConfigIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)):
    existing = await get_provider_config(db, "keycloak")
    data = body.model_dump()
    for key in ("client_secret", "admin_client_secret"):
        if data.get(key) == "********":
            data[key] = existing.get(key, "")
    await save_provider_config(db, "keycloak", body.enabled, data)
    await refresh_auth_sync_schedules()
    return {"ok": True}


@router.post("/keycloak/sync")
async def sync_keycloak_ad(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)):
    cfg = await get_provider_config(db, "keycloak")
    if not cfg.get("enabled"):
        raise HTTPException(400, "Keycloak is not enabled")
    try:
        return await sync_keycloak_directory(db, cfg)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Keycloak sync failed: {exc}") from exc


@router.get("/providers/status")
async def providers_status(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    ldap = await get_provider_config(db, "ldap")
    kc = await get_provider_config(db, "keycloak")
    return {
        "ldap": {"enabled": ldap.get("enabled", False)},
        "keycloak": {"enabled": kc.get("enabled", False)},
    }
