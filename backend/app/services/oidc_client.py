"""Generic OIDC Authorization Code + PKCE helpers (security-hardened)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from jose import JWTError, jwk, jwt

from app.branding import OIDC_STATE_COOKIE_NAME
from app.config import get_settings
from app.services.auth_urls import public_api_base, validate_frontend_url

STATE_COOKIE_NAME = OIDC_STATE_COOKIE_NAME
STATE_TTL_SECONDS = 600
CLOCK_SKEW_SECONDS = 60
ALLOWED_ALGS = ("RS256", "ES256")
DEFAULT_SCOPES = "openid profile email"
CALLBACK_PATH = "/api/auth/oidc/callback"

_JWKS_CACHE: dict[str, dict] = {}
_JWKS_CACHE_TS: dict[str, float] = {}
_JWKS_CACHE_TTL = 600
_DISCOVERY_CACHE: dict[str, dict] = {}
_DISCOVERY_CACHE_TS: dict[str, float] = {}
_DISCOVERY_CACHE_TTL = 300


@dataclass
class OIDCFlowParams:
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str


def default_oidc_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "issuer": "",
        "client_id": "",
        "client_secret": "",
        "scopes": DEFAULT_SCOPES,
        "claim_username": "preferred_username",
        "claim_email": "email",
        "claim_display_name": "name",
    }


def pinned_redirect_uri() -> str:
    return f"{public_api_base()}{CALLBACK_PATH}"


def public_view(cfg: dict[str, Any]) -> dict[str, Any]:
    defaults = default_oidc_config()
    merged = {**defaults, **{k: v for k, v in (cfg or {}).items() if k in defaults or k == "enabled"}}
    try:
        redirect = pinned_redirect_uri()
    except ValueError:
        redirect = f"http://localhost:8080{CALLBACK_PATH}"
    secret = str(merged.get("client_secret") or "")
    return {
        "enabled": bool(merged.get("enabled")),
        "issuer": str(merged.get("issuer") or ""),
        "client_id": str(merged.get("client_id") or ""),
        "client_secret": "********" if secret else "",
        "redirect_uri": redirect,
        "scopes": str(merged.get("scopes") or DEFAULT_SCOPES),
        "claim_username": str(merged.get("claim_username") or "preferred_username"),
        "claim_email": str(merged.get("claim_email") or "email"),
        "claim_display_name": str(merged.get("claim_display_name") or "name"),
    }


def validate_issuer_url(issuer: str, *, for_production: bool | None = None) -> str:
    env = getattr(get_settings(), "environment", "development")
    prod = env == "production" if for_production is None else for_production
    url = (issuer or "").strip().rstrip("/")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError("Invalid Issuer URL") from exc
    if (
        not parsed.scheme
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid Issuer URL")
    if prod:
        if parsed.scheme != "https":
            raise ValueError("Issuer URL must be HTTPS in production")
        if _hostname_is_blocked_ssrf(parsed.hostname):
            raise ValueError("Issuer URL host is not allowed")
    elif parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid Issuer URL")
    return url


def _hostname_is_blocked_ssrf(hostname: str) -> bool:
    settings = get_settings()
    if getattr(settings, "allow_ssrf_private_ranges", False):
        return False
    host = (hostname or "").lower()
    if host in {"localhost", "metadata.google.internal"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — block well-known cloud metadata names only; DNS pinning
        # at fetch time is handled by httpx timeout + validate_issuer scheme.
        return host.endswith(".internal") or host == "metadata"
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip == ipaddress.ip_address("169.254.169.254")
    )


def validate_oidc_config(cfg: dict[str, Any], *, enabled: bool | None = None) -> dict[str, Any]:
    """Normalize config for persistence. ``client_secret`` must already be resolved (not mask)."""
    is_enabled = bool(cfg.get("enabled") if enabled is None else enabled)
    issuer_raw = (cfg.get("issuer") or "").strip()
    issuer = validate_issuer_url(issuer_raw) if issuer_raw or is_enabled else ""
    client_id = (cfg.get("client_id") or "").strip()
    if is_enabled and not client_id:
        raise ValueError("Client ID is required when OIDC is enabled")
    if is_enabled and not issuer:
        raise ValueError("Issuer URL is required when OIDC is enabled")
    scopes = (cfg.get("scopes") or DEFAULT_SCOPES).strip() or DEFAULT_SCOPES
    if "openid" not in scopes.split():
        scopes = f"openid {scopes}".strip()
    return {
        "issuer": issuer,
        "client_id": client_id,
        "client_secret": str(cfg.get("client_secret") or "").strip(),
        "scopes": scopes,
        "claim_username": (cfg.get("claim_username") or "preferred_username").strip(),
        "claim_email": (cfg.get("claim_email") or "email").strip(),
        "claim_display_name": (cfg.get("claim_display_name") or "name").strip(),
    }


def _random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_flow_params() -> OIDCFlowParams:
    code_verifier = _random_token(48)
    return OIDCFlowParams(
        state=_random_token(32),
        nonce=_random_token(32),
        code_verifier=code_verifier,
        code_challenge=_pkce_challenge(code_verifier),
    )


def _hmac_key() -> bytes:
    secret = (get_settings().secret_key or "").encode("utf-8")
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured; cannot sign OIDC state.")
    return secret


def sign_state_cookie(params: OIDCFlowParams) -> str:
    payload = {
        "state": params.state,
        "nonce": params.nonce,
        "cv": params.code_verifier,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_hmac_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_state_cookie(cookie_value: str | None, state: str) -> OIDCFlowParams | None:
    if not cookie_value or not state:
        return None
    try:
        body, sig = cookie_value.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_hmac_key(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if not hmac.compare_digest(str(payload.get("state", "")), str(state)):
        return None
    cv = str(payload.get("cv", ""))
    if not cv:
        return None
    return OIDCFlowParams(
        state=str(payload["state"]),
        nonce=str(payload["nonce"]),
        code_verifier=cv,
        code_challenge=_pkce_challenge(cv),
    )


def state_cookie_params() -> dict:
    return {
        "key": STATE_COOKIE_NAME,
        "httponly": True,
        "secure": getattr(get_settings(), "environment", "development") == "production",
        "samesite": "lax",
        "max_age": STATE_TTL_SECONDS,
        "path": "/api/auth/oidc",
    }


def clear_state_cookie_params() -> dict:
    return {**state_cookie_params(), "max_age": 0, "expires": 0}


def fetch_discovery(issuer: str) -> dict[str, Any]:
    issuer_n = validate_issuer_url(issuer)
    now = time.time()
    cached = _DISCOVERY_CACHE.get(issuer_n)
    if cached is not None and (now - _DISCOVERY_CACHE_TS.get(issuer_n, 0)) < _DISCOVERY_CACHE_TTL:
        return cached
    url = f"{issuer_n}/.well-known/openid-configuration"
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if not data.get("authorization_endpoint") or not data.get("token_endpoint"):
        raise ValueError("OIDC discovery missing authorization/token endpoints")
    _DISCOVERY_CACHE[issuer_n] = data
    _DISCOVERY_CACHE_TS[issuer_n] = now
    return data


def build_authorize_url(cfg: dict[str, Any], params: OIDCFlowParams) -> str:
    issuer = validate_issuer_url(cfg.get("issuer") or "")
    discovery = fetch_discovery(issuer)
    auth_ep = discovery["authorization_endpoint"]
    redirect_uri = pinned_redirect_uri()
    scopes = (cfg.get("scopes") or DEFAULT_SCOPES).strip()
    if "openid" not in scopes.split():
        scopes = f"openid {scopes}".strip()
    q = {
        "client_id": cfg["client_id"],
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": params.state,
        "nonce": params.nonce,
        "code_challenge": params.code_challenge,
        "code_challenge_method": "S256",
    }
    sep = "&" if "?" in auth_ep else "?"
    return f"{auth_ep}{sep}{urlencode(q)}"


def exchange_code_for_tokens(cfg: dict[str, Any], *, code: str, code_verifier: str) -> dict[str, Any]:
    issuer = validate_issuer_url(cfg.get("issuer") or "")
    discovery = fetch_discovery(issuer)
    token_ep = discovery["token_endpoint"]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pinned_redirect_uri(),
        "client_id": cfg["client_id"],
        "code_verifier": code_verifier,
    }
    secret = (cfg.get("client_secret") or "").strip()
    headers = {"Accept": "application/json"}
    auth = None
    if secret:
        # Prefer body client_secret for broad IdP compatibility.
        data["client_secret"] = secret
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        resp = client.post(token_ep, data=data, headers=headers, auth=auth)
        if resp.status_code != 200:
            raise ValueError("OIDC token exchange failed")
        tokens = resp.json()
    if not tokens.get("id_token"):
        raise ValueError("OIDC did not return an ID token")
    return tokens


def _fetch_jwks(jwks_uri: str) -> dict:
    now = time.time()
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached is not None and (now - _JWKS_CACHE_TS.get(jwks_uri, 0)) < _JWKS_CACHE_TTL:
        return cached
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        resp = client.get(jwks_uri)
        resp.raise_for_status()
        data = resp.json()
    _JWKS_CACHE[jwks_uri] = data
    _JWKS_CACHE_TS[jwks_uri] = now
    return data


def validate_id_token(
    id_token: str,
    *,
    issuer: str,
    audience: str,
    nonce: str,
) -> dict[str, Any]:
    issuer_n = validate_issuer_url(issuer)
    discovery = fetch_discovery(issuer_n)
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        raise ValueError("OIDC discovery missing jwks_uri")
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise ValueError("Malformed ID token header") from exc
    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        raise ValueError("ID token algorithm not allowed")
    kid = header.get("kid")
    jwks = _fetch_jwks(jwks_uri)
    key_data = None
    for k in jwks.get("keys", []):
        if kid and k.get("kid") == kid:
            key_data = k
            break
    if key_data is None and len(jwks.get("keys", [])) == 1:
        key_data = jwks["keys"][0]
    if key_data is None:
        _JWKS_CACHE.pop(jwks_uri, None)
        jwks = _fetch_jwks(jwks_uri)
        for k in jwks.get("keys", []):
            if kid and k.get("kid") == kid:
                key_data = k
                break
    if key_data is None:
        raise ValueError("ID token signing key not found")
    try:
        key = jwk.construct(key_data)
        claims = jwt.decode(
            id_token,
            key,
            algorithms=list(ALLOWED_ALGS),
            audience=audience,
            issuer=issuer_n,
            options={
                "require_aud": True,
                "require_iss": True,
                "require_exp": True,
                "require_sub": True,
                "leeway": CLOCK_SKEW_SECONDS,
            },
        )
    except JWTError as exc:
        raise ValueError("ID token validation failed") from exc
    token_nonce = claims.get("nonce")
    if not token_nonce or not hmac.compare_digest(str(token_nonce), str(nonce)):
        raise ValueError("ID token nonce mismatch")
    nbf = claims.get("nbf")
    if nbf is not None and int(nbf) > int(time.time()) + CLOCK_SKEW_SECONDS:
        raise ValueError("ID token not yet valid")
    if not claims.get("sub"):
        raise ValueError("ID token missing subject")
    return claims


def fetch_userinfo(cfg: dict[str, Any], access_token: str) -> dict[str, Any]:
    issuer = validate_issuer_url(cfg.get("issuer") or "")
    discovery = fetch_discovery(issuer)
    userinfo_ep = discovery.get("userinfo_endpoint")
    if not userinfo_ep or not access_token:
        return {}
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        resp = client.get(userinfo_ep, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code != 200:
            return {}
        return resp.json()


def build_profile_from_claims(
    cfg: dict[str, Any],
    claims: dict[str, Any],
    userinfo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    info = userinfo or {}
    if info.get("sub") and claims.get("sub") and str(info.get("sub")) != str(claims.get("sub")):
        raise ValueError("OIDC subject mismatch")
    # Prefer ID token for identity fields; fill gaps from userinfo.
    def pick(claim_key: str, *alts: str) -> str | None:
        for key in (claim_key, *alts):
            for src in (claims, info):
                val = src.get(key)
                if val is not None and str(val).strip():
                    return str(val).strip()
        return None

    username_claim = (cfg.get("claim_username") or "preferred_username").strip()
    email_claim = (cfg.get("claim_email") or "email").strip()
    name_claim = (cfg.get("claim_display_name") or "name").strip()
    username = pick(username_claim, "preferred_username", "email", "sub")
    email = pick(email_claim, "email")
    display_name = pick(name_claim, "name")
    if not username:
        raise ValueError("OIDC profile missing username")
    return {
        "username": username,
        "email": email,
        "display_name": display_name or username,
        "external_id": str(claims["sub"]),
    }


def end_session_url(cfg: dict[str, Any], *, id_token_hint: str | None = None) -> str | None:
    try:
        issuer = validate_issuer_url(cfg.get("issuer") or "")
        discovery = fetch_discovery(issuer)
    except Exception:
        return None
    ep = discovery.get("end_session_endpoint")
    if not ep:
        return None
    frontend = validate_frontend_url(get_settings().frontend_url)
    q = {
        "client_id": cfg.get("client_id") or "",
        "post_logout_redirect_uri": f"{frontend}/login",
    }
    if id_token_hint:
        q["id_token_hint"] = id_token_hint
    sep = "&" if "?" in ep else "?"
    return f"{ep}{sep}{urlencode(q)}"


def clear_caches() -> None:
    _JWKS_CACHE.clear()
    _JWKS_CACHE_TS.clear()
    _DISCOVERY_CACHE.clear()
    _DISCOVERY_CACHE_TS.clear()
