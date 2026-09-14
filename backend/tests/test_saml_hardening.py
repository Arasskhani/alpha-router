"""SAML SP hardening: locked security flags, InResponseTo binding, replay refusal.

A throwaway IdP key pair is generated per module and real Responses are built
and signed with python3-saml's own utilities, so the negative cases exercise
the library's validation path rather than mocks of it.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from onelogin.saml2.utils import OneLogin_Saml2_Utils

from app.services import saml_sp, saml_state

SP_BASE = "https://alpha-router.example"
IDP_ENTITY = "https://idp.example.com/metadata"
IDP_SSO = "https://idp.example.com/sso"
ACS = f"{SP_BASE}/api/auth/saml/acs"
SP_ENTITY = f"{SP_BASE}/api/auth/saml/metadata"


# --------------------------------------------------------------------------- IdP fixture


def _make_idp_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.com")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, cert_pem


IDP_KEY, IDP_CERT = _make_idp_keypair()


def _idp_metadata_xml() -> str:
    cert_body = "".join(line for line in IDP_CERT.splitlines() if "CERTIFICATE" not in line)
    return f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{IDP_ENTITY}">
  <md:IDPSSODescriptor WantAuthnRequestsSigned="false" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data><ds:X509Certificate>{cert_body}</ds:X509Certificate></ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>
    <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified</md:NameIDFormat>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{IDP_SSO}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""


def _cfg(**overrides) -> dict:
    cfg = {
        "enabled": True,
        "idp_metadata_xml": _idp_metadata_xml(),
        "idp_metadata_url": "",
        "entity_id": SP_ENTITY,
        "attr_username": saml_sp.DEFAULT_ATTR_USERNAME,
        "attr_email": saml_sp.DEFAULT_ATTR_EMAIL,
        "attr_display_name": saml_sp.DEFAULT_ATTR_DISPLAY_NAME,
        "strict": True,
        "want_assertions_signed": True,
    }
    cfg.update(overrides)
    return cfg


def _ts(delta_seconds: int) -> str:
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta_seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_response(
    *,
    in_response_to: str | None,
    sign_assertion: bool = True,
    assertion_id: str | None = None,
    name_id: str = "alice@example.com",
) -> str:
    """Return a base64 SAMLResponse (HTTP-POST binding)."""
    resp_id = "_" + uuid.uuid4().hex
    asn_id = assertion_id or ("_" + uuid.uuid4().hex)
    irt_resp = f' InResponseTo="{in_response_to}"' if in_response_to else ""
    irt_scd = f' InResponseTo="{in_response_to}"' if in_response_to else ""
    assertion = f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xs="http://www.w3.org/2001/XMLSchema"
      ID="{asn_id}" Version="2.0" IssueInstant="{_ts(0)}">
    <saml:Issuer>{IDP_ENTITY}</saml:Issuer>
    <saml:Subject>
      <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified">{name_id}</saml:NameID>
      <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
        <saml:SubjectConfirmationData NotOnOrAfter="{_ts(300)}" Recipient="{ACS}"{irt_scd}/>
      </saml:SubjectConfirmation>
    </saml:Subject>
    <saml:Conditions NotBefore="{_ts(-60)}" NotOnOrAfter="{_ts(300)}">
      <saml:AudienceRestriction><saml:Audience>{SP_ENTITY}</saml:Audience></saml:AudienceRestriction>
    </saml:Conditions>
    <saml:AuthnStatement AuthnInstant="{_ts(0)}" SessionIndex="{resp_id}">
      <saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef></saml:AuthnContext>
    </saml:AuthnStatement>
    <saml:AttributeStatement>
      <saml:Attribute Name="{saml_sp.DEFAULT_ATTR_USERNAME}"><saml:AttributeValue xsi:type="xs:string">alice</saml:AttributeValue></saml:Attribute>
      <saml:Attribute Name="{saml_sp.DEFAULT_ATTR_EMAIL}"><saml:AttributeValue xsi:type="xs:string">{name_id}</saml:AttributeValue></saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>"""
    if sign_assertion:
        # Sign the Assertion element itself (what wantAssertionsSigned checks),
        # the way most IdPs do; the Response envelope stays unsigned.
        signed = OneLogin_Saml2_Utils.add_sign(assertion, IDP_KEY, IDP_CERT)
        assertion = signed.decode() if isinstance(signed, bytes) else signed
        if assertion.startswith("<?xml"):
            assertion = assertion.split("?>", 1)[1]
    xml = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    ID="{resp_id}" Version="2.0" IssueInstant="{_ts(0)}" Destination="{ACS}"{irt_resp}>
  <saml:Issuer>{IDP_ENTITY}</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  {assertion}
</samlp:Response>"""
    raw = xml.encode()
    return base64.b64encode(raw).decode()


@pytest.fixture(autouse=True)
def _public_base(monkeypatch):
    monkeypatch.setattr(saml_sp, "public_api_base", lambda: SP_BASE)
    yield


# --------------------------------------------------------------------------- locked flags


def test_security_flags_are_forced_on_by_default(monkeypatch):
    monkeypatch.setattr(saml_sp, "get_settings", lambda: SimpleNamespace(allow_insecure_saml=False))
    sec = saml_sp._security_settings({"want_assertions_signed": False, "strict": False})
    assert sec["wantAssertionsSigned"] is True
    settings = saml_sp.build_sp_only_settings({"strict": False, "entity_id": SP_ENTITY})
    assert settings["strict"] is True
    view = saml_sp.public_view({"strict": False, "want_assertions_signed": False})
    assert view["strict"] is True and view["want_assertions_signed"] is True
    assert view["security_locked"] is True
    saved = saml_sp.validate_saml_config(
        {"enabled": False, "entity_id": SP_ENTITY, "strict": False, "want_assertions_signed": False}
    )
    assert saved["strict"] is True and saved["want_assertions_signed"] is True


def test_security_flags_follow_admin_only_with_lab_override(monkeypatch):
    monkeypatch.setattr(saml_sp, "get_settings", lambda: SimpleNamespace(allow_insecure_saml=True))
    sec = saml_sp._security_settings({"want_assertions_signed": False})
    assert sec["wantAssertionsSigned"] is False
    assert saml_sp.public_view({})["security_locked"] is False


# --------------------------------------------------------------------------- SP flow


def test_login_returns_request_id_that_the_redirect_carries():
    url, request_id = saml_sp.login_redirect_url(_cfg(), f"{SP_BASE}/api/auth/saml/login")
    assert url.startswith(IDP_SSO)
    assert request_id.startswith("ONELOGIN_") and len(request_id) > 20


def test_peek_in_response_to_reads_the_attribute_and_tolerates_junk():
    assert saml_sp.peek_in_response_to(_build_response(in_response_to="_abc")) == "_abc"
    assert saml_sp.peek_in_response_to(_build_response(in_response_to=None)) is None
    assert saml_sp.peek_in_response_to("not base64!!") is None
    assert saml_sp.peek_in_response_to(base64.b64encode(b"<broken").decode()) is None


def test_signed_response_bound_to_request_is_accepted():
    _, request_id = saml_sp.login_redirect_url(_cfg(), f"{SP_BASE}/api/auth/saml/login")
    b64 = _build_response(in_response_to=request_id)
    profile = saml_sp.process_acs(_cfg(), ACS, {"SAMLResponse": b64}, request_id=request_id)
    assert profile["username"] == "alice"
    assert profile["external_id"] == "alice@example.com"
    assert profile["assertion_id"].startswith("_")
    assert profile["assertion_not_on_or_after"] is not None


def test_unsigned_assertion_is_rejected():
    _, request_id = saml_sp.login_redirect_url(_cfg(), f"{SP_BASE}/api/auth/saml/login")
    b64 = _build_response(in_response_to=request_id, sign_assertion=False)
    with pytest.raises(ValueError, match="validation failed"):
        saml_sp.process_acs(_cfg(), ACS, {"SAMLResponse": b64}, request_id=request_id)


def test_unsigned_assertion_is_rejected_even_if_admin_unticked_the_box(monkeypatch):
    monkeypatch.setattr(saml_sp, "get_settings", lambda: SimpleNamespace(allow_insecure_saml=False))
    cfg = _cfg(want_assertions_signed=False, strict=False)
    _, request_id = saml_sp.login_redirect_url(cfg, f"{SP_BASE}/api/auth/saml/login")
    b64 = _build_response(in_response_to=request_id, sign_assertion=False)
    with pytest.raises(ValueError, match="validation failed"):
        saml_sp.process_acs(cfg, ACS, {"SAMLResponse": b64}, request_id=request_id)


def test_in_response_to_mismatch_is_rejected_by_the_library():
    _, request_id = saml_sp.login_redirect_url(_cfg(), f"{SP_BASE}/api/auth/saml/login")
    b64 = _build_response(in_response_to="_someone_elses_request")
    with pytest.raises(ValueError, match="InResponseTo"):
        saml_sp.process_acs(_cfg(), ACS, {"SAMLResponse": b64}, request_id=request_id)


def test_unsolicited_response_is_refused_before_validation():
    b64 = _build_response(in_response_to=None)
    with pytest.raises(ValueError, match="unsolicited"):
        saml_sp.process_acs(_cfg(), ACS, {"SAMLResponse": b64}, request_id=None)


# --------------------------------------------------------------------------- state store


class _FakeRedis:
    """Just enough of redis.asyncio for the two operations the store uses."""

    store: dict[str, str] = {}
    fail = False

    async def set(self, key, value, ex=None, nx=False):
        if self.fail:
            raise ConnectionError("redis down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return 1 if self.store.pop(key, None) is not None else 0

    async def aclose(self):
        return None


@pytest.fixture
def fake_redis(monkeypatch):
    _FakeRedis.store = {}
    _FakeRedis.fail = False
    saml_state.set_client_factory(_FakeRedis)
    monkeypatch.setattr(saml_state, "get_settings", lambda: SimpleNamespace(saml_request_ttl_seconds=600))
    yield _FakeRedis
    saml_state.set_client_factory(None)


def test_request_is_consumed_exactly_once(fake_redis):
    async def run():
        await saml_state.remember_authn_request("_r1")
        assert await saml_state.consume_authn_request("_r1") is True
        assert await saml_state.consume_authn_request("_r1") is False
        assert await saml_state.consume_authn_request("_never_issued") is False
        assert await saml_state.consume_authn_request(None) is False

    asyncio.run(run())


def test_assertion_id_is_accepted_once(fake_redis):
    async def run():
        assert await saml_state.register_assertion("_a1", None) is True
        assert await saml_state.register_assertion("_a1", None) is False
        assert await saml_state.register_assertion("", None) is False

    asyncio.run(run())


def test_store_fails_closed_without_redis(fake_redis):
    fake_redis.fail = True

    async def run():
        with pytest.raises(saml_state.SamlStateUnavailable):
            await saml_state.remember_authn_request("_r1")
        with pytest.raises(saml_state.SamlStateUnavailable):
            await saml_state.consume_authn_request("_r1")

    asyncio.run(run())


# --------------------------------------------------------------------------- ACS endpoint


def _acs_request():
    return SimpleNamespace(url=SimpleNamespace(path="/api/auth/saml/acs"), client=SimpleNamespace(host="10.0.0.9"))


def test_acs_endpoint_refuses_replay_of_the_same_response(fake_redis, monkeypatch):
    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api, "_request_public_url", lambda request: ACS)
    cfg = _cfg()
    db = AsyncMock()
    user = SimpleNamespace(id=1, username="alice", token_version=0, is_active=True)
    audit = AsyncMock()

    async def run():
        with (
            patch.object(auth_api, "get_provider_config", new=AsyncMock(return_value=cfg)),
            patch.object(auth_api, "_upsert_directory_user", new=AsyncMock(return_value=user)),
            patch.object(auth_api, "get_user_role_slugs", new=AsyncMock(return_value=["user"])),
            patch.object(auth_api, "record_user_login", new=AsyncMock()),
            patch.object(auth_api, "store_token", new=AsyncMock()),
            patch.object(auth_api, "validate_frontend_url", lambda url: SP_BASE),
            patch("app.services.security_audit.log_security_event", new=audit),
        ):
            # Real login step: issues and remembers the request id.
            _, request_id = saml_sp.login_redirect_url(cfg, f"{SP_BASE}/api/auth/saml/login")
            await saml_state.remember_authn_request(request_id)
            b64 = _build_response(in_response_to=request_id)

            first = await auth_api.saml_acs(_acs_request(), b64, None, db)
            assert first.status_code in (302, 307)
            assert "/login?code=" in first.headers["location"]

            # Same Response again: the request id is gone.
            with pytest.raises(HTTPException) as exc:
                await auth_api.saml_acs(_acs_request(), b64, None, db)
            assert exc.value.status_code == 401
            assert "outstanding login request" in exc.value.detail
            assert audit.await_args.kwargs["detail"] == {"reason": "unsolicited_or_replayed_response"}

            # Even with a fresh request id, an already-seen assertion is refused.
            _, request_id2 = saml_sp.login_redirect_url(cfg, f"{SP_BASE}/api/auth/saml/login")
            await saml_state.remember_authn_request(request_id2)
            first_assertion_id = next(k for k in fake_redis.store if k.startswith("saml:asn:")).split(":", 2)[2]
            replay = _build_response(in_response_to=request_id2, assertion_id=first_assertion_id)
            with pytest.raises(HTTPException) as exc2:
                await auth_api.saml_acs(_acs_request(), replay, None, db)
            assert exc2.value.status_code == 401
            assert "already used" in exc2.value.detail

    asyncio.run(run())


def test_acs_endpoint_refuses_idp_initiated_response(fake_redis, monkeypatch):
    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api, "_request_public_url", lambda request: ACS)
    db = AsyncMock()

    async def run():
        with (
            patch.object(auth_api, "get_provider_config", new=AsyncMock(return_value=_cfg())),
            patch("app.services.security_audit.log_security_event", new=AsyncMock()),
        ):
            with pytest.raises(HTTPException) as exc:
                await auth_api.saml_acs(_acs_request(), _build_response(in_response_to=None), None, db)
            assert exc.value.status_code == 401

    asyncio.run(run())


def test_acs_and_login_answer_503_when_redis_is_down(fake_redis, monkeypatch):
    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api, "_request_public_url", lambda request: ACS)
    fake_redis.fail = True
    db = AsyncMock()

    async def run():
        with patch.object(auth_api, "get_provider_config", new=AsyncMock(return_value=_cfg())):
            with pytest.raises(HTTPException) as exc:
                await auth_api.saml_login(_acs_request(), db)
            assert exc.value.status_code == 503
            with pytest.raises(HTTPException) as exc2:
                await auth_api.saml_acs(_acs_request(), _build_response(in_response_to="_x"), None, db)
            assert exc2.value.status_code == 503

    asyncio.run(run())
