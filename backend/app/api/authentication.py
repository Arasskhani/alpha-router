"""Admin UI: configure LDAP, SAML 2.0, and generic OIDC."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_authentication, require_authentication_write
from app.database import get_db
from app.models.auth_provider import AuthProviderConfig
from app.models.user import User
from app.services.auth_config import decrypt_provider_config, get_provider_config, save_provider_config
from app.services.auth_sync_scheduler import refresh_auth_sync_schedules
from app.services.ldap_auth import test_ldap_connection
from app.services.ldap_config import (
    LDAPS_PORT,
    merge_simple_ldap_config,
    parse_sync_ous,
    resolve_password,
    simple_public_view,
)
from app.services.ldap_sync import sync_ldap_directory
from app.services.oidc_client import (
    DEFAULT_SCOPES,
    validate_oidc_config,
)
from app.services.oidc_client import (
    public_view as oidc_public_view,
)
from app.services.saml_sp import (
    DEFAULT_ATTR_DISPLAY_NAME,
    DEFAULT_ATTR_EMAIL,
    DEFAULT_ATTR_USERNAME,
    validate_saml_config,
)
from app.services.saml_sp import (
    public_view as saml_public_view,
)

router = APIRouter(prefix="/api/admin/authentication", tags=["authentication"])


class LdapSimpleIn(BaseModel):
    enabled: bool = False
    dc_host: str = ""
    bind_username: str = ""
    bind_password: str = ""
    # Accepted for backward-compatible clients; always forced to LDAPS server-side.
    port: int = Field(default=LDAPS_PORT, ge=1, le=65535)
    use_ssl: bool = True
    trust_untrusted_cert: bool = False
    sync_ous: str = ""
    sync_ous_prune: bool = False
    sync_schedule_enabled: bool = False
    sync_schedule_hour: int = Field(default=3, ge=0, le=23)
    sync_schedule_minute: int = Field(default=0, ge=0, le=59)


class SamlConfigIn(BaseModel):
    enabled: bool = False
    idp_metadata_url: str = ""
    idp_metadata_xml: str = ""
    entity_id: str = ""
    attr_username: str = DEFAULT_ATTR_USERNAME
    attr_email: str = DEFAULT_ATTR_EMAIL
    attr_display_name: str = DEFAULT_ATTR_DISPLAY_NAME
    strict: bool = True
    want_assertions_signed: bool = True


class OidcConfigIn(BaseModel):
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = DEFAULT_SCOPES
    claim_username: str = "preferred_username"
    claim_email: str = "email"
    claim_display_name: str = "name"


@router.get("/ldap")
async def get_ldap(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    row = await db.get(AuthProviderConfig, "ldap")
    if row and row.config_json:
        raw = decrypt_provider_config("ldap", {"enabled": row.enabled, **json.loads(row.config_json)})
    else:
        raw = await get_provider_config(db, "ldap")
    return simple_public_view(raw)


@router.put("/ldap")
async def save_ldap(
    body: LdapSimpleIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)
):
    existing_row = await db.get(AuthProviderConfig, "ldap")
    existing: dict = {}
    if existing_row and existing_row.config_json:
        existing = decrypt_provider_config("ldap", json.loads(existing_row.config_json))

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
            LDAPS_PORT,
            use_ssl=True,
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
        await db.rollback()
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        # Leave the session usable: after a failed flush it stays inactive
        # until it is rolled back, and the dependency reuses it for this request.
        await db.rollback()
        raise HTTPException(400, f"LDAP sync failed: {e}") from e


@router.post("/ldap/test")
async def test_ldap(
    body: LdapSimpleIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_authentication_write),
):
    """Bind with the service account and run a small LDAP query over LDAPS."""
    existing_row = await db.get(AuthProviderConfig, "ldap")
    existing: dict = {}
    if existing_row and existing_row.config_json:
        existing = decrypt_provider_config("ldap", json.loads(existing_row.config_json))

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
            LDAPS_PORT,
            use_ssl=True,
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
        "port": result.get("port") or LDAPS_PORT,
        "use_ssl": True,
        "encryption": result.get("encryption") or "LDAPS",
    }


@router.get("/saml")
async def get_saml(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    cfg = await get_provider_config(db, "saml")
    return saml_public_view(cfg)


@router.put("/saml")
async def save_saml(
    body: SamlConfigIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)
):
    try:
        data = validate_saml_config(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await save_provider_config(db, "saml", body.enabled, data)
    return {"ok": True, **saml_public_view({**data, "enabled": body.enabled})}


@router.get("/oidc")
async def get_oidc(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    cfg = await get_provider_config(db, "oidc")
    return oidc_public_view(cfg)


@router.put("/oidc")
async def save_oidc(
    body: OidcConfigIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication_write)
):
    existing = await get_provider_config(db, "oidc")
    data = body.model_dump()
    if data.get("client_secret") == "********":
        data["client_secret"] = existing.get("client_secret", "")
    try:
        saved = validate_oidc_config(data, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await save_provider_config(db, "oidc", body.enabled, saved)
    return {"ok": True, **oidc_public_view({**saved, "enabled": body.enabled})}


@router.get("/providers/status")
async def providers_status(db: AsyncSession = Depends(get_db), _: User = Depends(require_authentication)):
    ldap = await get_provider_config(db, "ldap")
    saml = await get_provider_config(db, "saml")
    oidc = await get_provider_config(db, "oidc")
    return {
        "ldap": {"enabled": ldap.get("enabled", False)},
        "saml": {"enabled": saml.get("enabled", False)},
        "oidc": {"enabled": oidc.get("enabled", False)},
    }
