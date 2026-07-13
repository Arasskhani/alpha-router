"""Phase 6: OIDC primitives — state cookie, PKCE, realm validation, ID-token (JWKS).

The ID-token validation test generates a real RSA keypair, builds a JWKS, mocks
the JWKS fetch, signs an ID token with the private key, and asserts the
validator accepts a well-formed token and rejects tampered iss/aud/nonce/exp.
"""

import asyncio
import json
import time
from unittest.mock import patch

import pytest
from jose import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import base64

from app.services import oidc


def _b64url_int(i: int) -> str:
    b = i.to_bytes((i.bit_length() + 7) // 8 or 1, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _make_keypair_and_jwks():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    pub_numbers = pub.public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "test-kid",
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_int(pub_numbers.n),
        "e": _b64url_int(pub_numbers.e),
    }
    jwks = {"keys": [jwk]}
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, jwks


def _patch_settings(env: str = "development", secret: str = "test-secret-key-for-oidc"):
    class _S:
        environment = env
        secret_key = secret
    return patch("app.services.oidc.get_settings", return_value=_S())


# --- state cookie + PKCE ------------------------------------------------------

def test_pkce_challenge_is_s256_base64url():
    p = oidc.generate_flow_params()
    # challenge is base64url without padding, 43 chars for S256
    assert len(p.code_challenge) == 43
    assert "=" not in p.code_challenge
    assert p.state != p.nonce != p.code_verifier


def test_state_cookie_roundtrip():
    with _patch_settings():
        p = oidc.generate_flow_params()
        val = oidc.sign_state_cookie(p)
        out = oidc.verify_state_cookie(val, p.state)
    assert out is not None
    assert out.state == p.state
    assert out.nonce == p.nonce
    assert out.code_verifier == p.code_verifier


def test_state_cookie_rejects_state_mismatch():
    with _patch_settings():
        p = oidc.generate_flow_params()
        val = oidc.sign_state_cookie(p)
        assert oidc.verify_state_cookie(val, "wrong-state") is None


def test_state_cookie_rejects_tampered_signature():
    with _patch_settings():
        p = oidc.generate_flow_params()
        val = oidc.sign_state_cookie(p)
        tampered = val[:-2] + ("AA" if not val.endswith("AA") else "BB")
        assert oidc.verify_state_cookie(tampered, p.state) is None


def test_state_cookie_rejects_expired():
    with _patch_settings():
        p = oidc.generate_flow_params()
        val = oidc.sign_state_cookie(p)
    # Patch time so the cookie is in the past.
    with patch("app.services.oidc.time.time", return_value=time.time() + oidc.STATE_TTL_SECONDS + 1):
        assert oidc.verify_state_cookie(val, p.state) is None


def test_state_cookie_rejects_missing_cookie():
    with _patch_settings():
        assert oidc.verify_state_cookie("", "x") is None
        assert oidc.verify_state_cookie(None, "x") is None


# --- realm / server_url validation -------------------------------------------

def test_validate_realm_rejects_path_injection():
    with _patch_settings():
        for bad in ("master/../other", "a/b", "a b", "..", ""):
            with pytest.raises(ValueError):
                oidc.validate_realm(bad)
        assert oidc.validate_realm("alpha-router") == "alpha-router"


def test_validate_server_url_https_in_production():
    with _patch_settings(env="production"):
        with pytest.raises(ValueError):
            oidc.validate_server_url("http://keycloak.internal")
        assert oidc.validate_server_url("https://keycloak.example.com") == "https://keycloak.example.com"
    with _patch_settings(env="development"):
        assert oidc.validate_server_url("http://localhost:8090") == "http://localhost:8090"


def test_redirect_origins_reject_credentials_query_and_fragments():
    with _patch_settings():
        for bad in (
            "https://user:secret@keycloak.example.com",
            "https://keycloak.example.com?next=https://evil.example",
            "https://keycloak.example.com/#fragment",
            "javascript:alert(1)",
            "//keycloak.example.com",
        ):
            with pytest.raises(ValueError):
                oidc.validate_server_url(bad)
        assert oidc.validate_frontend_url("http://localhost:8080") == "http://localhost:8080"
        assert (
            oidc.validate_oidc_redirect_uri("http://localhost:8080/api/auth/keycloak/callback")
            == "http://localhost:8080/api/auth/keycloak/callback"
        )
        with pytest.raises(ValueError):
            oidc.validate_oidc_redirect_uri("https://user:pass@evil.example/callback")


def test_frontend_redirect_requires_https_in_production():
    with _patch_settings(env="production"):
        with pytest.raises(ValueError):
            oidc.validate_frontend_url("http://alpha-router.example.com")
        assert (
            oidc.validate_frontend_url("https://alpha-router.example.com/app")
            == "https://alpha-router.example.com/app"
        )


# --- ID token validation (JWKS) ----------------------------------------------

def _sign_id_token(pem, claims):
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-kid"})


def test_validate_id_token_accepts_well_formed():
    pem, jwks = _make_keypair_and_jwks()
    issuer = "https://kc.example.com/realms/alpha-router"
    nonce = "nonce-123"
    claims = {
        "iss": issuer,
        "aud": "alpha-router-ui",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "sub": "user-sub-42",
        "nonce": nonce,
    }
    token = _sign_id_token(pem, claims)
    with _patch_settings():
        with patch("app.services.oidc._fetch_jwks", return_value=jwks):
            out = oidc.validate_id_token(token, issuer=issuer, audience="alpha-router-ui", nonce=nonce)
    assert out["sub"] == "user-sub-42"


def test_validate_id_token_rejects_wrong_issuer():
    pem, jwks = _make_keypair_and_jwks()
    claims = {
        "iss": "https://kc.example.com/realms/alpha-router",
        "aud": "alpha-router-ui",
        "exp": int(time.time()) + 300,
        "sub": "x",
        "nonce": "n",
    }
    token = _sign_id_token(pem, claims)
    with _patch_settings():
        with patch("app.services.oidc._fetch_jwks", return_value=jwks):
            with pytest.raises(ValueError):
                oidc.validate_id_token(token, issuer="https://kc.example.com/realms/other", audience="alpha-router-ui", nonce="n")


def test_validate_id_token_rejects_wrong_audience():
    pem, jwks = _make_keypair_and_jwks()
    issuer = "https://kc.example.com/realms/alpha-router"
    claims = {"iss": issuer, "aud": "alpha-router-ui", "exp": int(time.time()) + 300, "sub": "x", "nonce": "n"}
    token = _sign_id_token(pem, claims)
    with _patch_settings():
        with patch("app.services.oidc._fetch_jwks", return_value=jwks):
            with pytest.raises(ValueError):
                oidc.validate_id_token(token, issuer=issuer, audience="wrong-client", nonce="n")


def test_validate_id_token_rejects_nonce_mismatch():
    pem, jwks = _make_keypair_and_jwks()
    issuer = "https://kc.example.com/realms/alpha-router"
    claims = {"iss": issuer, "aud": "alpha-router-ui", "exp": int(time.time()) + 300, "sub": "x", "nonce": "n"}
    token = _sign_id_token(pem, claims)
    with _patch_settings():
        with patch("app.services.oidc._fetch_jwks", return_value=jwks):
            with pytest.raises(ValueError):
                oidc.validate_id_token(token, issuer=issuer, audience="alpha-router-ui", nonce="different")


def test_validate_id_token_rejects_expired():
    pem, jwks = _make_keypair_and_jwks()
    issuer = "https://kc.example.com/realms/alpha-router"
    claims = {"iss": issuer, "aud": "alpha-router-ui", "exp": int(time.time()) - 10, "sub": "x", "nonce": "n"}
    token = _sign_id_token(pem, claims)
    with _patch_settings():
        with patch("app.services.oidc._fetch_jwks", return_value=jwks):
            with pytest.raises(ValueError):
                oidc.validate_id_token(token, issuer=issuer, audience="alpha-router-ui", nonce="n")
