"""OIDC (Keycloak) helpers: state, PKCE, nonce, JWKS-based ID-token validation.

These primitives harden the authorization-code flow used by the Keycloak SSO
login:

* ``state`` — random, stored in a short-lived signed cookie, echoed back by the
  IdP and verified on the callback to prevent login CSRF.
* ``code_verifier`` / ``code_challenge`` (PKCE S256) — protects the
  authorization-code exchange even if the code is leaked; defense-in-depth on
  top of the confidential client secret.
* ``nonce`` — random, sent to the authorize endpoint and validated inside the
  ID token to bind the token to this auth request and prevent replay.
* ID-token validation — issuer, audience, expiry, nonce, and signature via the
  realm JWKS (public key cached).

The signed state cookie carries ``state``, ``nonce`` and ``code_verifier`` so
the callback can re-derive them without server-side session storage. It is
HMAC-signed with the app ``SECRET_KEY`` (tamper-evident) and short-lived.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import JWTError, jwt
from jose.utils import base64url_decode

from app.config import get_settings

# Cookie names (namespaced so they cannot collide with other cookies).
STATE_COOKIE_NAME = "nitro_oidc_state"
# TTL for the state cookie / one-time-flow window, in seconds.
STATE_TTL_SECONDS = 600

_JWKS_CACHE: dict[str, dict] = {}
_JWKS_CACHE_TS: dict[str, float] = {}
_JWKS_CACHE_TTL = 600  # 10 minutes


@dataclass
class OIDCFlowParams:
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str


def _random_token(nbytes: int = 32) -> str:
    import secrets

    return secrets.token_urlsafe(nbytes)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_flow_params() -> OIDCFlowParams:
    """Generate a fresh state/nonce/PKCE triplet for one authorization request."""
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


def _b64(s: bytes) -> str:
    return base64.urlsafe_b64encode(s).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_state_cookie(params: OIDCFlowParams) -> str:
    """Return the signed cookie value carrying state/nonce/code_verifier + exp."""
    payload = {
        "state": params.state,
        "nonce": params.nonce,
        "cv": params.code_verifier,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    import hmac

    sig = hmac.new(_hmac_key(), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(sig)}"


def verify_state_cookie(cookie_value: str, state: str) -> OIDCFlowParams | None:
    """Validate the signed cookie and the ``state`` returned by the IdP.

    Returns the flow params if the cookie signature is valid, the cookie has not
    expired, and ``state`` matches. Returns ``None`` otherwise (callers should
    reject the callback).
    """
    if not cookie_value or "." not in cookie_value:
        return None
    raw_b64, sig_b64 = cookie_value.split(".", 1)
    try:
        raw = _unb64(raw_b64)
        sig = _unb64(sig_b64)
    except Exception:
        return None
    import hmac

    expected = hmac.new(_hmac_key(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if not hmac.compare_digest(str(payload.get("state", "")), str(state)):
        return None
    return OIDCFlowParams(
        state=str(payload["state"]),
        nonce=str(payload["nonce"]),
        code_verifier=str(payload["cv"]),
        code_challenge=_pkce_challenge(str(payload["cv"])),
    )


def state_cookie_params() -> dict:
    """Return Set-Cookie kwargs for the OIDC state cookie (top-level redirect safe)."""
    return {
        "key": STATE_COOKIE_NAME,
        "httponly": True,
        "secure": getattr(get_settings(), "environment", "development") == "production",
        "samesite": "lax",  # sent on top-level cross-site redirect from IdP
        "max_age": STATE_TTL_SECONDS,
        "path": "/api/auth/keycloak",
    }


def clear_state_cookie_params() -> dict:
    return {**state_cookie_params(), "max_age": 0, "expires": 0}


def validate_realm(realm: str) -> str:
    """Reject realm names that could inject path segments into the IdP URL."""
    if not realm or "/" in realm or "\\" in realm or ".." in realm or " " in realm:
        raise ValueError("Invalid Keycloak realm")
    return realm


def validate_server_url(server_url: str) -> str:
    """Require https in production; accept http only in development."""
    env = getattr(get_settings(), "environment", "development")
    url = (server_url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid Keycloak server URL")
    if env == "production" and not url.startswith("https://"):
        raise ValueError("Keycloak server URL must be HTTPS in production")
    return url.rstrip("/")


def issuer_for(server_url: str, realm: str) -> str:
    return f"{validate_server_url(server_url)}/realms/{validate_realm(realm)}"


def _fetch_jwks(issuer: str) -> dict:
    """Fetch (and cache) the realm JWKS."""
    now = time.time()
    cached = _JWKS_CACHE.get(issuer)
    if cached is not None and (now - _JWKS_CACHE_TS.get(issuer, 0)) < _JWKS_CACHE_TTL:
        return cached
    jwks_url = f"{issuer}/protocol/openid-connect/certs"
    resp = httpx.get(jwks_url, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    _JWKS_CACHE[issuer] = data
    _JWKS_CACHE_TS[issuer] = now
    return data


def _find_key(jwks: dict, kid: str | None) -> dict | None:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def validate_id_token(
    id_token: str,
    *,
    issuer: str,
    audience: str,
    nonce: str,
) -> dict:
    """Validate an OIDC ID token: signature (JWKS), iss, aud, exp, nonce.

    Returns the decoded claims on success; raises ``ValueError`` on any
    validation failure so callers can surface a clean 401.
    """
    try:
        unverified_header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise ValueError("Malformed ID token header") from exc
    kid = unverified_header.get("kid")
    try:
        jwks = _fetch_jwks(issuer)
    except Exception as exc:
        raise ValueError("Could not fetch IdP signing keys") from exc
    key = _find_key(jwks, kid)
    if key is None:
        # Refresh once in case of a key rotation.
        _JWKS_CACHE.pop(issuer, None)
        _JWKS_CACHE_TS.pop(issuer, None)
        try:
            jwks = _fetch_jwks(issuer)
        except Exception as exc:
            raise ValueError("Could not fetch IdP signing keys") from exc
        key = _find_key(jwks, kid)
    if key is None:
        raise ValueError("ID token signing key not found in JWKS")
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require_aud": True, "require_iss": True, "require_exp": True},
        )
    except JWTError as exc:
        raise ValueError(f"ID token validation failed: {exc}") from exc
    token_nonce = claims.get("nonce")
    if not token_nonce or token_nonce != nonce:
        raise ValueError("ID token nonce mismatch")
    return claims
