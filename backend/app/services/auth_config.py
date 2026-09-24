"""Load authentication provider settings from database."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.auth_provider import AuthProviderConfig
from app.services.ldap_config import expand_ldap_config
from app.services.oidc_client import default_oidc_config
from app.services.saml_sp import default_saml_config
from app.services.saml_sp import public_view as saml_public_view
from app.services.secret_crypto import decrypt_secret, encrypt_typed_secret

settings = get_settings()

# Fields inside each provider's config_json that hold live credentials and must
# be encrypted at rest. Everything else stays plaintext.
_SENSITIVE_FIELDS: dict[str, set[str]] = {
    "ldap": {"bind_password"},
    "oidc": {"client_secret"},
}


def _encrypt_config_fields(provider: str, payload: dict) -> dict:
    """Encrypt the credential fields of a config about to be saved.

    Callers hand over plaintext only (the saved config is decrypted before it is
    merged with the form), so each value is encrypted as it is. The general
    ``encrypt_secret`` keeps a value that already is ciphertext unchanged, which
    here would let a stored token typed into the form be saved, decrypted at
    sign-in into the secret it holds, and sent to the server the form names.
    """
    sensitive = _SENSITIVE_FIELDS.get(provider, set())
    if not sensitive:
        return payload
    out = dict(payload)
    for k in sensitive:
        if out.get(k):
            out[k] = encrypt_typed_secret(out[k])
    return out


def decrypt_provider_config(provider: str, payload: dict) -> dict:
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
        if provider == "saml":
            return {**saml_public_view(raw), "enabled": bool(raw.get("enabled"))}
        if provider == "oidc":
            # Keep decrypted secret for runtime; admin endpoints mask separately.
            return {**raw, "enabled": bool(raw.get("enabled"))}
        return raw
    fallback = _env_fallback(provider)
    if provider == "ldap":
        return expand_ldap_config(fallback)
    if provider == "saml":
        return {**saml_public_view(fallback), "enabled": bool(fallback.get("enabled"))}
    if provider == "oidc":
        return fallback
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
            "use_ssl": True,
        }
    if provider == "saml":
        base = default_saml_config()
        base["enabled"] = bool(settings.saml_enabled)
        if settings.saml_idp_metadata_url:
            base["idp_metadata_url"] = settings.saml_idp_metadata_url
        if settings.saml_entity_id:
            base["entity_id"] = settings.saml_entity_id
        return base
    if provider == "oidc":
        base = default_oidc_config()
        base["enabled"] = bool(getattr(settings, "oidc_enabled", False))
        if getattr(settings, "oidc_issuer", ""):
            base["issuer"] = settings.oidc_issuer
        if getattr(settings, "oidc_client_id", ""):
            base["client_id"] = settings.oidc_client_id
        if getattr(settings, "oidc_client_secret", ""):
            base["client_secret"] = settings.oidc_client_secret
        return base
    return {"enabled": False}


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
