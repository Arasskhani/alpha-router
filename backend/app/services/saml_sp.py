"""SAML 2.0 Service Provider helpers (python3-saml)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from app.services.auth_urls import public_api_base

logger = logging.getLogger(__name__)

ACS_PATH = "/api/auth/saml/acs"
METADATA_PATH = "/api/auth/saml/metadata"
SLO_PATH = "/api/auth/saml/logout"

DEFAULT_ATTR_USERNAME = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
DEFAULT_ATTR_EMAIL = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
DEFAULT_ATTR_DISPLAY_NAME = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname"


def default_saml_config() -> dict[str, Any]:
    try:
        base = public_api_base()
    except ValueError:
        base = "http://localhost:8080"
    return {
        "enabled": False,
        "idp_metadata_url": "",
        "idp_metadata_xml": "",
        "entity_id": f"{base}{METADATA_PATH}",
        "attr_username": DEFAULT_ATTR_USERNAME,
        "attr_email": DEFAULT_ATTR_EMAIL,
        "attr_display_name": DEFAULT_ATTR_DISPLAY_NAME,
        "strict": True,
        "want_assertions_signed": True,
    }


def acs_url() -> str:
    return f"{public_api_base()}{ACS_PATH}"


def metadata_url() -> str:
    return f"{public_api_base()}{METADATA_PATH}"


def slo_url() -> str:
    return f"{public_api_base()}{SLO_PATH}"


def public_view(cfg: dict[str, Any]) -> dict[str, Any]:
    defaults = default_saml_config()
    merged = {**defaults, **{k: v for k, v in (cfg or {}).items() if k in defaults or k == "enabled"}}
    return {
        "enabled": bool(merged.get("enabled")),
        "idp_metadata_url": str(merged.get("idp_metadata_url") or ""),
        "idp_metadata_xml": str(merged.get("idp_metadata_xml") or ""),
        "entity_id": str(merged.get("entity_id") or defaults["entity_id"]),
        "acs_url": acs_url() if _safe_public_base() else f"http://localhost:8080{ACS_PATH}",
        "metadata_url": metadata_url() if _safe_public_base() else f"http://localhost:8080{METADATA_PATH}",
        "attr_username": str(merged.get("attr_username") or DEFAULT_ATTR_USERNAME),
        "attr_email": str(merged.get("attr_email") or DEFAULT_ATTR_EMAIL),
        "attr_display_name": str(merged.get("attr_display_name") or DEFAULT_ATTR_DISPLAY_NAME),
        "strict": bool(merged.get("strict", True)),
        "want_assertions_signed": bool(merged.get("want_assertions_signed", True)),
    }


def _safe_public_base() -> bool:
    try:
        public_api_base()
        return True
    except ValueError:
        return False


def validate_saml_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate admin-submitted SAML config."""
    view = public_view(cfg)
    url = (view.get("idp_metadata_url") or "").strip()
    xml = (view.get("idp_metadata_xml") or "").strip()
    if view["enabled"] and not url and not xml:
        raise ValueError("IdP Metadata URL or IdP Metadata XML is required when SAML is enabled")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid IdP Metadata URL")
    entity_id = (view.get("entity_id") or "").strip()
    if not entity_id:
        raise ValueError("SP Entity ID is required")
    return {
        "idp_metadata_url": url,
        "idp_metadata_xml": xml,
        "entity_id": entity_id,
        "attr_username": (view.get("attr_username") or DEFAULT_ATTR_USERNAME).strip(),
        "attr_email": (view.get("attr_email") or DEFAULT_ATTR_EMAIL).strip(),
        "attr_display_name": (view.get("attr_display_name") or DEFAULT_ATTR_DISPLAY_NAME).strip(),
        "strict": bool(view.get("strict", True)),
        "want_assertions_signed": bool(view.get("want_assertions_signed", True)),
    }


def _load_idp_data(cfg: dict[str, Any]) -> dict[str, Any]:
    """Load IdP settings. URL takes precedence over uploaded/stored XML when both are set."""
    xml = (cfg.get("idp_metadata_xml") or "").strip()
    url = (cfg.get("idp_metadata_url") or "").strip()
    if url:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            parsed = OneLogin_Saml2_IdPMetadataParser.parse(resp.text)
        return parsed.get("idp") or {}
    if xml:
        parsed = OneLogin_Saml2_IdPMetadataParser.parse(xml)
        return parsed.get("idp") or {}
    raise ValueError("IdP metadata is not configured")


def _security_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    want_signed = bool(cfg.get("want_assertions_signed", True))
    return {
        "nameIdEncrypted": False,
        "authnRequestsSigned": False,
        "logoutRequestSigned": False,
        "logoutResponseSigned": False,
        "signMetadata": False,
        "wantMessagesSigned": False,
        "wantAssertionsSigned": want_signed,
        "wantAssertionsEncrypted": False,
        "wantNameId": True,
        "wantNameIdEncrypted": False,
        "requestedAuthnContext": False,
        "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
        "rejectDeprecatedAlgorithm": True,
        "allowSingleLabelDomains": True,
    }


def _sp_settings_block(cfg: dict[str, Any]) -> dict[str, Any]:
    entity_id = (cfg.get("entity_id") or "").strip() or metadata_url()
    return {
        "entityId": entity_id,
        "assertionConsumerService": {
            "url": acs_url(),
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        },
        "singleLogoutService": {
            "url": slo_url(),
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        },
        "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
        "x509cert": "",
        "privateKey": "",
    }


def build_sp_only_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """Settings sufficient to emit SP metadata — no IdP required."""
    return {
        "strict": bool(cfg.get("strict", True)),
        "debug": False,
        "sp": _sp_settings_block(cfg),
        # Placeholder IdP so python3-saml accepts the settings object; not used for metadata.
        "idp": {
            "entityId": "https://idp.placeholder.invalid",
            "singleSignOnService": {
                "url": "https://idp.placeholder.invalid/sso",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": "",
        },
        "security": _security_settings(cfg),
    }


def build_saml_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    idp = _load_idp_data(cfg)
    if not idp.get("entityId") or not idp.get("singleSignOnService", {}).get("url"):
        raise ValueError("IdP metadata is missing entityId or SSO URL")
    return {
        "strict": bool(cfg.get("strict", True)),
        "debug": False,
        "sp": _sp_settings_block(cfg),
        "idp": idp,
        "security": _security_settings(cfg),
    }


def prepare_request_data(request_url: str, form: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> dict:
    """Build the request dict expected by python3-saml from a FastAPI Request."""
    parsed = urlsplit(request_url)
    https = "on" if parsed.scheme == "https" else "off"
    # Prefer X-Forwarded headers when behind a reverse proxy — callers should
    # pass the public URL already; fall back to parsed components.
    host = parsed.hostname or "localhost"
    if parsed.port and not ((parsed.scheme == "https" and parsed.port == 443) or (parsed.scheme == "http" and parsed.port == 80)):
        server_port = str(parsed.port)
    else:
        server_port = "443" if https == "on" else "80"
    return {
        "https": https,
        "http_host": host,
        "server_port": server_port,
        "script_name": parsed.path,
        "get_data": query or {},
        "post_data": form or {},
    }


def _auth_from_request(cfg: dict[str, Any], req: dict) -> OneLogin_Saml2_Auth:
    settings = build_saml_settings(cfg)
    return OneLogin_Saml2_Auth(req, old_settings=settings)


def login_redirect_url(cfg: dict[str, Any], request_url: str) -> str:
    req = prepare_request_data(request_url)
    auth = _auth_from_request(cfg, req)
    return auth.login()


def process_acs(cfg: dict[str, Any], request_url: str, form: dict[str, Any]) -> dict[str, Any]:
    """Validate SAMLResponse and return a normalized profile dict."""
    req = prepare_request_data(request_url, form=form)
    auth = _auth_from_request(cfg, req)
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        reason = auth.get_last_error_reason() or "; ".join(errors)
        raise ValueError(f"SAML assertion validation failed: {reason}")
    if not auth.is_authenticated():
        raise ValueError("SAML assertion was not authenticated")

    name_id = (auth.get_nameid() or "").strip()
    attrs = auth.get_attributes() or {}
    username = _first_attr(attrs, cfg.get("attr_username")) or name_id
    email = _first_attr(attrs, cfg.get("attr_email"))
    display_name = _first_attr(attrs, cfg.get("attr_display_name"))
    if not username:
        raise ValueError("SAML response did not include a username or NameID")
    if not name_id:
        raise ValueError("SAML response is missing NameID (required as external identity)")
    return {
        "username": username,
        "email": email,
        "display_name": display_name or username,
        "external_id": name_id,
    }


def sp_metadata_xml(cfg: dict[str, Any]) -> str:
    """Generate SP metadata XML without requiring IdP configuration."""
    settings = OneLogin_Saml2_Settings(settings=build_sp_only_settings(cfg), sp_validation_only=True)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise ValueError(f"Invalid SP metadata: {'; '.join(errors)}")
    return metadata.decode("utf-8") if isinstance(metadata, bytes) else str(metadata)


def logout_redirect_url(cfg: dict[str, Any], request_url: str, name_id: str | None = None) -> str | None:
    """Return IdP SLO URL when metadata provides it; otherwise None (local logout only)."""
    try:
        idp = _load_idp_data(cfg)
    except Exception:
        return None
    slo = (idp.get("singleLogoutService") or {}).get("url")
    if not slo:
        return None
    req = prepare_request_data(request_url)
    auth = _auth_from_request(cfg, req)
    try:
        return auth.logout(name_id=name_id or "")
    except Exception:
        logger.exception("SAML SLO init failed")
        return None


def _first_attr(attrs: dict[str, Any], key: str | None) -> str | None:
    if not key:
        return None
    values = attrs.get(key)
    if values is None:
        # Also try short local-name matches (some IdPs omit the URI).
        short = key.rsplit("/", 1)[-1].rsplit("}", 1)[-1]
        for k, v in attrs.items():
            if k == key or k.endswith(short) or k.rsplit("/", 1)[-1] == short:
                values = v
                break
    if not values:
        return None
    if isinstance(values, (list, tuple)):
        if not values:
            return None
        return str(values[0]).strip() or None
    return str(values).strip() or None
