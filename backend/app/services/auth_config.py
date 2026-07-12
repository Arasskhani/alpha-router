"""Load authentication provider settings from database."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_provider import AuthProviderConfig
from app.services.ldap_config import expand_ldap_config
from app.services.secret_crypto import decrypt_secret, encrypt_secret

settings = get_settings()

# Fields inside each provider's config_json that hold live credentials and must
# be encrypted at rest. Everything else (hosts, DNs, ports, schedules) stays
# plaintext so admins can read it back and so direct DB inspection still works.
_SENSITIVE_FIELDS: dict[str, set[str]] = {
    "ldap": {"bind_password"},
    "keycloak": {"client_secret", "admin_client_secret"},
}


def _encrypt_config_fields(provider: str, payload: dict) -> dict:
    """Return a copy of ``payload`` with sensitive fields encrypted (idempotent)."""
    sensitive = _SENSITIVE_FIELDS.get(provider, set())
    if not sensitive:
        return payload
    out = dict(payload)
    for k in sensitive:
        if out.get(k):
            out[k] = encrypt_secret(out[k])
    return out


def decrypt_provider_config(provider: str, payload: dict) -> dict:
    """Return a copy of ``payload`` with sensitive fields decrypted.

    Used by ``get_provider_config`` and by admin endpoints that read
    ``config_json`` directly (so they never see ciphertext for ``resolve_password``
    or test-bind flows, which would otherwise double-encrypt on save).
    """
    sensitive = _SENSITIVE_FIELDS.get(provider, set())
    if not sensitive:
        return payload
    out = dict(payload)
    for k in sensitive:
        if out.get(k):
            out[k] = decrypt_secret(out[k])
    return out


async def get_provider_config(db: AsyncSession, provider: str) -> dict:
    row = await db.get(AuthProviderConfig, provider)
    if row and row.config_json:
        raw = {"enabled": row.enabled, **json.loads(row.config_json)}
        raw = decrypt_provider_config(provider, raw)
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
    payload = _encrypt_config_fields(provider, payload)
    if not row:
        row = AuthProviderConfig(provider=provider, enabled=enabled, config_json=json.dumps(payload))
        db.add(row)
    else:
        row.enabled = enabled
        row.config_json = json.dumps(payload)
    await db.commit()
