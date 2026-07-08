"""Load authentication provider settings from database."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_provider import AuthProviderConfig
from app.services.ldap_config import expand_ldap_config

settings = get_settings()


async def get_provider_config(db: AsyncSession, provider: str) -> dict:
    row = await db.get(AuthProviderConfig, provider)
    if row and row.config_json:
        raw = {"enabled": row.enabled, **json.loads(row.config_json)}
        if provider == "ldap":
            return expand_ldap_config(raw)
        return raw
    fallback = _env_fallback(provider)
    if provider == "ldap":
        return expand_ldap_config(fallback)
    return fallback


def _env_fallback(provider: str) -> dict:
    if provider == "ldap":
        return {
            "enabled": settings.ldap_enabled,
            "server": settings.ldap_server,
            "base_dn": settings.ldap_base_dn,
            "bind_dn": settings.ldap_bind_dn,
            "bind_password": settings.ldap_bind_password,
            "dc_host": settings.ldap_server.split("://")[-1].split(":")[0] if settings.ldap_server else "",
            "bind_username": settings.ldap_bind_dn,
            "port": 636,
        }
    return {
        "enabled": settings.keycloak_enabled,
        "server_url": settings.keycloak_server_url,
        "realm": settings.keycloak_realm,
        "client_id": settings.keycloak_client_id,
        "client_secret": settings.keycloak_client_secret,
        "redirect_uri": settings.keycloak_redirect_uri,
        "admin_client_id": "",
        "admin_client_secret": "",
    }


async def save_provider_config(db: AsyncSession, provider: str, enabled: bool, config: dict) -> None:
    row = await db.get(AuthProviderConfig, provider)
    payload = {k: v for k, v in config.items() if k != "enabled"}
    if not row:
        row = AuthProviderConfig(provider=provider, enabled=enabled, config_json=json.dumps(payload))
        db.add(row)
    else:
        row.enabled = enabled
        row.config_json = json.dumps(payload)
    await db.commit()
