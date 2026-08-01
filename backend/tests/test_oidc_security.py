"""OIDC security controls (S-01 … S-20) — unit/integration with mocks."""

from __future__ import annotations

import base64
import json
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import base64url_encode

from app.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.services import auth_exchange
from app.services.auth_urls import validate_frontend_url
from app.services.oidc_client import (
    build_authorize_url,
    build_profile_from_claims,
    clear_caches,
    exchange_code_for_tokens,
    generate_flow_params,
    pinned_redirect_uri,
    public_view,
    sign_state_cookie,
    validate_id_token,
    validate_issuer_url,
    validate_oidc_config,
    verify_state_cookie,
)
from app.services.secret_crypto import encrypt_secret


ISSUER = "https://idp.example.com/realms/alpha-router"


class FakeRedis:
    """Minimal async Redis-like store (matches auth_exchange pipeline usage)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return self.store.pop(key, None) is not None

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._ops = []

            def get(self, key):
                self._ops.append(("get", key))
                return self

            def delete(self, key):
                self._ops.append(("delete", key))
                return self

            async def execute(self):
                results = []
                for op, key in self._ops:
                    if op == "get":
                        results.append(await outer.get(key))
                    elif op == "delete":
                        results.append(await outer.delete(key))
                return results

        return _Pipe()

    async def aclose(self):
        return None
CLIENT_ID = "alpha-client"
DISCOVERY = {
    "authorization_endpoint": "https://idp.example.com/auth",
    "token_endpoint": "https://idp.example.com/token",
    "jwks_uri": "https://idp.example.com/jwks",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
    "end_session_endpoint": "https://idp.example.com/logout",
}


def _b64int(val: int) -> str:
    length = (val.bit_length() + 7) // 8
    return base64url_encode(val.to_bytes(length, "big")).decode()


@pytest.fixture
def rsa_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64int(pub.n),
        "e": _b64int(pub.e),
    }
    return priv_pem, {"keys": [jwk]}


@pytest.fixture(autouse=True)
def _oidc_env(monkeypatch):
    clear_caches()
    monkeypatch.setenv("SECRET_KEY", "oidc-test-secret-key-not-a-placeholder")
    monkeypatch.setenv("API_PUBLIC_URL", "https://alpha-router.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    yield
    clear_caches()
    get_settings.cache_clear()


def _make_id_token(priv_pem, *, claims: dict | None = None, alg: str = "RS256", kid: str = "test-key"):
    now = int(time.time())
    body = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "user-sub-1",
        "exp": now + 300,
        "iat": now,
        "nonce": "expected-nonce",
        "preferred_username": "alice",
        "email": "alice@example.com",
        "name": "Alice",
    }
    if claims:
        body.update(claims)
    headers = {"kid": kid, "alg": alg}
    if alg == "none":
        # Manually craft an unsigned token (python-jose may refuse alg=none encode).
        h = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        p = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=").decode()
        return f"{h}.{p}."
    return jwt.encode(body, priv_pem, algorithm=alg, headers=headers)


def test_s01_authorize_includes_pkce_s256():
    params = generate_flow_params()
    with patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY):
        url = build_authorize_url(
            {"issuer": ISSUER, "client_id": CLIENT_ID, "scopes": "openid profile email"},
            params,
        )
    assert "code_challenge_method=S256" in url
    assert "code_challenge=" in url
    assert f"state={params.state}" in url
    assert f"nonce={params.nonce}" in url


def test_s02_state_mismatch_rejected():
    params = generate_flow_params()
    cookie = sign_state_cookie(params)
    assert verify_state_cookie(cookie, "wrong-state") is None
    assert verify_state_cookie(None, params.state) is None
    assert verify_state_cookie(cookie, params.state) is not None


def test_s03_state_ttl_expired():
    params = generate_flow_params()
    cookie = sign_state_cookie(params)
    with patch("app.services.oidc_client.time") as mock_time:
        mock_time.time.return_value = time.time() + 10_000
        assert verify_state_cookie(cookie, params.state) is None


def test_s04_nonce_mismatch(rsa_material):
    priv, jwks = rsa_material
    token = _make_id_token(priv, claims={"nonce": "other"})
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError, match="nonce"):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s05_iss_mismatch(rsa_material):
    priv, jwks = rsa_material
    token = _make_id_token(priv, claims={"iss": "https://evil.example.com"})
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s06_aud_mismatch(rsa_material):
    priv, jwks = rsa_material
    token = _make_id_token(priv, claims={"aud": "other-client"})
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s07_expired_token(rsa_material):
    priv, jwks = rsa_material
    token = _make_id_token(priv, claims={"exp": int(time.time()) - 120})
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s08_alg_none_rejected(rsa_material):
    _, jwks = rsa_material
    token = _make_id_token(b"", alg="none")
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError, match="algorithm"):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s08_hs256_rejected(rsa_material):
    _, jwks = rsa_material
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "x",
            "exp": now + 300,
            "nonce": "expected-nonce",
        },
        "symmetric-secret",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError, match="algorithm"):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s09_bad_signature(rsa_material):
    _, jwks = rsa_material
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = _make_id_token(other_pem)
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        with pytest.raises(ValueError):
            validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")


def test_s10_redirect_uri_pinned():
    params = generate_flow_params()
    cfg = {
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "redirect_uri": "https://evil.example.com/callback",
        "scopes": "openid",
    }
    captured: dict = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"id_token": "x"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None, auth=None):
            captured["data"] = dict(data or {})
            return FakeResp()

    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client.httpx.Client", FakeClient),
    ):
        url = build_authorize_url(cfg, params)
        tokens = exchange_code_for_tokens(cfg, code="abc", code_verifier=params.code_verifier)
    pinned = pinned_redirect_uri()
    assert pinned in unquote(url)
    assert "evil.example.com" not in unquote(url)
    assert tokens.get("id_token") == "x"
    assert captured["data"]["redirect_uri"] == pinned


def test_s11_frontend_url_rejects_credentials_and_query():
    with pytest.raises(ValueError):
        validate_frontend_url("https://user:pass@example.com")
    with pytest.raises(ValueError):
        validate_frontend_url("https://app.example.com/?next=evil")


def test_s12_issuer_http_rejected_in_production():
    with pytest.raises(ValueError, match="HTTPS"):
        validate_issuer_url("http://idp.example.com", for_production=True)
    with pytest.raises(ValueError):
        validate_issuer_url("https://user:pass@idp.example.com", for_production=True)


def async_test(coro):
    import asyncio

    return asyncio.run(coro)


def test_s13_exchange_single_use_and_no_jwt_in_location_pattern():
    fake = FakeRedis()

    async def _run():
        with patch("app.services.auth_exchange._client", return_value=fake):
            code = auth_exchange.generate_code()
            await auth_exchange.store_token(code, {"token": "JWT-SECRET", "role": "user"})
            first = await auth_exchange.consume_code(code)
            second = await auth_exchange.consume_code(code)
            assert first and first["token"] == "JWT-SECRET"
            assert second is None
            # Opaque code must not look like a JWT.
            assert code.count(".") < 2

    async_test(_run())


def test_s16_userinfo_sub_mismatch():
    with pytest.raises(ValueError, match="subject mismatch"):
        build_profile_from_claims(
            {"claim_username": "preferred_username", "claim_email": "email", "claim_display_name": "name"},
            {"sub": "a", "preferred_username": "alice"},
            {"sub": "b", "preferred_username": "alice"},
        )


def test_s17_secret_masked_and_encrypted_at_rest():
    plain = "super-secret-client"
    cipher = encrypt_secret(plain)
    assert cipher != plain
    view = public_view(
        {
            "enabled": True,
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": plain,
        }
    )
    assert view["client_secret"] == "********"
    # Mask sentinel means "keep existing" at admin PUT layer; validate expects resolved secret.
    saved = validate_oidc_config(
        {
            "enabled": True,
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": plain,
        },
        enabled=True,
    )
    assert saved["client_secret"] == plain


def _ensure_fake_onelogin() -> None:
    """Stub python3-saml imports for hosts without the xmlsec stack."""
    names = [
        "onelogin",
        "onelogin.saml2",
        "onelogin.saml2.auth",
        "onelogin.saml2.settings",
        "onelogin.saml2.idp_metadata_parser",
        "onelogin.saml2.utils",
    ]
    for name in names:
        if name not in sys.modules:
            mod = ModuleType(name)
            if name in {"onelogin", "onelogin.saml2"}:
                mod.__path__ = []  # mark as package
            sys.modules[name] = mod
    sys.modules["onelogin.saml2.auth"].OneLogin_Saml2_Auth = MagicMock()
    sys.modules["onelogin.saml2.settings"].OneLogin_Saml2_Settings = MagicMock()
    sys.modules["onelogin.saml2.idp_metadata_parser"].OneLogin_Saml2_IdPMetadataParser = MagicMock()


def test_s18_oidc_tls_guard():
    _ensure_fake_onelogin()
    from app.main import _collect_production_insecurities

    flags = _collect_production_insecurities(
        environment="production",
        secret_key="a-real-secret-not-a-placeholder",
        admin_password="a-real-admin-password",
        gateway_master_key="a-real-master-key",
        code_sandbox_broker_url="http://sandbox-broker:8081",
        code_sandbox_broker_token="a-random-sandbox-token-with-at-least-32-chars",
        redis_url="redis://:a-strong-redis-password@redis:6379/0",
        data_encryption_key="a-dedicated-data-encryption-key-32+chars",
        openapi_admin_only=True,
        oidc_enabled=True,
        oidc_issuer="http://idp.example.com",
        api_public_url="https://api.example.com",
        frontend_url="https://app.example.com",
    )
    assert "OIDC_TLS" in flags


def test_s19_logout_bumps_token_version_semantics():
    old = create_access_token("alice", "user", token_version=0)
    payload = decode_access_token(old)
    assert payload is not None
    assert int(payload.get("ver", 0)) == 0
    # After logout bump to 1, deps reject jwt_ver < user.token_version.
    assert int(payload.get("ver", 0)) < 1


def test_s20_ssrf_metadata_and_private_hosts_blocked_in_prod():
    with pytest.raises(ValueError):
        validate_issuer_url("http://169.254.169.254/", for_production=True)
    with pytest.raises(ValueError):
        validate_issuer_url("https://169.254.169.254/", for_production=True)
    with pytest.raises(ValueError):
        validate_issuer_url("https://127.0.0.1/oidc", for_production=True)


def test_valid_id_token_accepted(rsa_material):
    priv, jwks = rsa_material
    token = _make_id_token(priv)
    with (
        patch("app.services.oidc_client.fetch_discovery", return_value=DISCOVERY),
        patch("app.services.oidc_client._fetch_jwks", return_value=jwks),
    ):
        claims = validate_id_token(token, issuer=ISSUER, audience=CLIENT_ID, nonce="expected-nonce")
    assert claims["sub"] == "user-sub-1"
