"""Every path that starts, refuses or ends a session writes exactly one row.

This is the specification the Sign-in Activity page is built on. Each test
drives one authentication path and asserts what it hands the recorder — the
event type, the outcome, the reason code, the method — with the recorder
itself replaced by a spy. The recorder's own behaviour (its independent
session, its refusal to raise) is covered in test_auth_events_service.py.

Before this table existed, five of these paths recorded nothing: a
rate-limited attempt, a SAML or OIDC sign-in, an SSO code that did not
exchange, and every revocation that was not an explicit sign-out. SSO
sign-outs are deliberately absent: the identity provider is the record of
those, and the page says so.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api import auth as auth_api


def _request(cookies=None) -> MagicMock:
    request = MagicMock()
    request.headers = {"user-agent": "spec"}
    request.client = SimpleNamespace(host="198.51.100.9")
    request.cookies = cookies or {}
    request.url = SimpleNamespace(path="/api/auth/x")
    return request


def _user(**over) -> SimpleNamespace:
    base = dict(
        id=7,
        username="ada",
        email="ada@x",
        hashed_password="$2b$hash",
        auth_provider="local",
        totp_enabled=False,
        is_active=True,
        deleted_at=None,
        token_version=3,
        totp_secret_encrypted=None,
        totp_backup_codes_hashed=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def recorded(monkeypatch):
    """Spy on the recorder wherever the handlers import it from."""

    spy = AsyncMock()
    monkeypatch.setattr(auth_api, "record_auth_event", spy)
    return spy


def _only_call(spy: AsyncMock) -> dict:
    assert spy.await_count == 1, f"expected exactly one auth event, got {spy.await_count}"
    return spy.await_args.kwargs


# --- login_local ------------------------------------------------------------


async def _login(body: dict, *, user, verify: bool, ldap_enabled=False, ldap_profile=None, ldap_error=None):
    ldap_cfg = {"enabled": ldap_enabled}

    def _auth_ldap(*_a, **_k):
        if ldap_error:
            raise ldap_error
        return ldap_profile

    with (
        patch("app.services.rate_limit.check_login_rate_limit", AsyncMock()),
        patch.object(auth_api, "find_user_by_username_ci", AsyncMock(return_value=user)),
        patch.object(auth_api, "verify_password", return_value=verify),
        patch.object(auth_api, "ensure_user_chat_store", AsyncMock()),
        patch.object(auth_api, "get_provider_config", AsyncMock(return_value=ldap_cfg)),
        patch.object(auth_api, "authenticate_ldap_sync", _auth_ldap),
        patch.object(auth_api, "_upsert_directory_user", AsyncMock(return_value=user)),
        patch.object(auth_api, "_token_response", AsyncMock(return_value="TOKEN")),
    ):
        return await auth_api.login_local(auth_api.LoginRequest(**body), _request(), MagicMock(), db=AsyncMock())


async def test_1_local_password_success_is_recorded_by_token_response(recorded):
    """Success is written where the token is minted, so every method shares it."""
    user = _user()
    token = auth_api.create_access_token("ada", "user", token_version=3)
    with (
        patch.object(auth_api, "create_access_token", return_value=token),
        patch.object(auth_api, "record_user_login", AsyncMock()),
        patch.object(auth_api, "get_user_role_slugs", AsyncMock(return_value=["user"])),
        patch.object(auth_api, "set_session_cookies"),
    ):
        await auth_api._token_response(AsyncMock(), user, MagicMock(), _request())
    call = _only_call(recorded)
    assert call["event_type"] == "login_success"
    assert call["auth_method"] == "local"
    assert call["user"] is user
    assert call["session_id"] == auth_api._jti(token), "the row must carry the session's jti"


async def test_2a_bad_password_on_a_local_account(recorded):
    with pytest.raises(HTTPException) as exc:
        await _login({"username": "ada", "password": "nope"}, user=_user(), verify=False)
    assert exc.value.status_code == 401
    call = _only_call(recorded)
    assert (call["event_type"], call["reason_code"], call["auth_method"]) == ("login_failed", "bad_password", "local")


async def test_2b_no_such_user_is_distinguishable_to_the_operator(recorded):
    """The person sees the same 401 either way; the administrator sees which."""
    with pytest.raises(HTTPException):
        await _login({"username": "ghost", "password": "x"}, user=None, verify=False)
    call = _only_call(recorded)
    assert call["reason_code"] == "no_such_user"
    assert call["user"] is None
    assert call["username"] == "ghost"


async def test_2c_a_deleted_account_names_the_account(recorded):
    user = _user(deleted_at="2026-01-01")
    with pytest.raises(HTTPException):
        await _login({"username": "ada", "password": "x"}, user=user, verify=False)
    call = _only_call(recorded)
    assert call["reason_code"] == "account_deleted"
    assert call["user"] is user


async def test_2d_ldap_said_no(recorded):
    user = _user(auth_provider="ldap", hashed_password=None)
    with pytest.raises(HTTPException):
        await _login(
            {"username": "ada", "password": "x"}, user=user, verify=False, ldap_enabled=True, ldap_profile=None
        )
    call = _only_call(recorded)
    assert (call["reason_code"], call["auth_method"]) == ("ldap_rejected", "ldap")


async def test_2e_ldap_unreachable_is_an_outage_not_an_attack(recorded):
    user = _user(auth_provider="ldap", hashed_password=None)
    with pytest.raises(HTTPException) as exc:
        await _login(
            {"username": "ada", "password": "x"},
            user=user,
            verify=False,
            ldap_enabled=True,
            ldap_error=auth_api.LdapUnavailableError("directory down"),
        )
    assert exc.value.status_code == 503
    call = _only_call(recorded)
    assert call["reason_code"] == "ldap_unavailable"
    assert "directory down" in call["reason_detail"]


async def test_3_a_rate_limited_attempt_is_the_one_brute_force_detection_needs(recorded):
    """The limiter raises before anything else runs; nothing else would write this."""
    limiter = AsyncMock(side_effect=HTTPException(status_code=429, detail="Too many attempts"))
    with patch("app.services.rate_limit.check_login_rate_limit", limiter):
        with pytest.raises(HTTPException) as exc:
            await auth_api.login_local(
                auth_api.LoginRequest(username="ada", password="x"), _request(), MagicMock(), db=AsyncMock()
            )
    assert exc.value.status_code == 429, "the row must not swallow the 429"
    call = _only_call(recorded)
    assert (call["event_type"], call["reason_code"]) == ("login_rate_limited", "rate_limited")
    assert call["username"] == "ada"


async def test_4_and_5_second_factor(recorded):
    """A wrong code is a failed sign-in; a right one reaches the shared success path."""
    user = _user(totp_enabled=True, totp_secret_encrypted="enc", totp_backup_codes_hashed=[])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(first=lambda: user)))
    from contextlib import ExitStack

    def _common(stack: ExitStack) -> None:
        stack.enter_context(patch("app.services.rate_limit.check_rate_limit", AsyncMock()))
        stack.enter_context(
            patch(
                "app.services.twofa_pending.consume_pending",
                AsyncMock(return_value={"user_id": 7, "purpose": "login_2fa"}),
            )
        )
        stack.enter_context(patch("app.services.totp_service.decrypt_totp_secret", return_value="secret"))
        stack.enter_context(patch("app.services.totp_service.consume_backup_code", return_value=None))
        stack.enter_context(patch.object(auth_api, "ensure_user_chat_store", AsyncMock()))

    body = auth_api.TwoFaLoginRequest(pending_token="p", code="000000")

    with ExitStack() as stack:
        _common(stack)
        stack.enter_context(patch("app.services.totp_service.verify_totp_code", return_value=False))
        with pytest.raises(HTTPException):
            await auth_api.login_2fa(body, _request(), MagicMock(), db=db)
    call = _only_call(recorded)
    assert (call["event_type"], call["reason_code"]) == ("login_failed", "twofa_failed")

    recorded.reset_mock()
    with ExitStack() as stack:
        _common(stack)
        stack.enter_context(patch("app.services.totp_service.verify_totp_code", return_value=True))
        success = stack.enter_context(patch.object(auth_api, "_token_response", AsyncMock(return_value="TOKEN")))
        await auth_api.login_2fa(body, _request(), MagicMock(), db=db)
    success.assert_awaited_once()
    assert recorded.await_count == 0, "success is recorded inside _token_response, not twice"


# --- SAML -----------------------------------------------------------------------


async def test_7_a_refused_saml_response_is_a_failed_sign_in_as_well(recorded):
    db = AsyncMock()
    with patch("app.services.security_audit.log_security_event", AsyncMock()):
        await auth_api._audit_saml_rejection(db, _request(), "assertion_invalid", "ref-1")
    call = _only_call(recorded)
    assert (call["event_type"], call["reason_code"], call["auth_method"]) == ("login_failed", "saml_rejected", "saml")
    assert call["reason_detail"] == "assertion_invalid"
    assert call["user"] is None


# --- SSO exchange --------------------------------------------------------------


async def test_12_an_sso_code_that_does_not_exchange(recorded):
    with patch.object(auth_api, "consume_code", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await auth_api._sso_exchange(auth_api.ExchangeRequest(code="stale"), MagicMock(), _request())
    assert exc.value.status_code == 401
    call = _only_call(recorded)
    assert (call["event_type"], call["reason_code"]) == ("login_failed", "sso_code_invalid")


async def test_a_successful_exchange_does_not_record_a_second_sign_in(recorded):
    """Success was recorded at the ACS / callback, where the account was resolved."""
    payload = {"token": "t", "role": "user", "is_active": True}
    with (
        patch.object(auth_api, "consume_code", AsyncMock(return_value=payload)),
        patch.object(auth_api, "set_session_cookies"),
    ):
        await auth_api._sso_exchange(auth_api.ExchangeRequest(code="ok"), MagicMock(), _request())
    assert recorded.await_count == 0


# --- logout ----------------------------------------------------------------------


async def test_9_signing_out_names_the_session_it_came_from_and_says_it_ended_all(recorded):
    user = _user()
    token = auth_api.create_access_token("ada", "user", token_version=3)
    request = _request(cookies={auth_api.settings.session_cookie_name: token})
    with (
        patch("app.services.presence_service.clear_presence", AsyncMock()),
        patch.object(auth_api, "clear_session_cookies"),
    ):
        await auth_api.logout_local(request, MagicMock(), user=user, db=AsyncMock())
    call = _only_call(recorded)
    assert call["event_type"] == "logout"
    assert call["session_id"] == auth_api._jti(token)
    assert user.token_version == 4, "logout still revokes everything"


# --- the paths that are deliberately not here -----------------------------------


def test_10_sso_sign_outs_are_the_identity_providers_record():
    """Decided, not forgotten: /oidc/logout and /saml/logout write no row."""
    import inspect

    for handler in (auth_api.oidc_logout, auth_api.saml_logout):
        assert "record_auth_event" not in inspect.getsource(handler)


# --- OIDC -------------------------------------------------------------------------


async def test_8a_an_oidc_callback_without_a_valid_state_is_a_failed_sign_in(recorded):
    with (
        patch.object(auth_api, "get_provider_config", AsyncMock(return_value={"enabled": True})),
        patch.object(auth_api, "verify_state_cookie", return_value=None),
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_api.oidc_callback(_request(), code="c", state="s", db=AsyncMock())
    assert exc.value.status_code == 400
    call = _only_call(recorded)
    assert (call["event_type"], call["reason_code"], call["auth_method"]) == ("login_failed", "oidc_rejected", "oidc")


async def test_8b_an_id_token_the_provider_rejects(recorded):
    flow = SimpleNamespace(code_verifier="v", nonce="n")
    with (
        patch.object(
            auth_api, "get_provider_config", AsyncMock(return_value={"enabled": True, "issuer": "i", "client_id": "c"})
        ),
        patch.object(auth_api, "verify_state_cookie", return_value=flow),
        patch.object(auth_api, "exchange_code_for_tokens", side_effect=ValueError("nonce mismatch")),
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_api.oidc_callback(_request(), code="c", state="s", db=AsyncMock())
    assert exc.value.status_code == 401
    call = _only_call(recorded)
    assert call["reason_code"] == "oidc_rejected"
    assert call["reason_detail"] == "nonce mismatch"


async def test_8c_an_unexpected_provider_error_records_the_class_not_the_message(recorded):
    """The message may carry a URL or a token; the class is enough to triage on."""
    flow = SimpleNamespace(code_verifier="v", nonce="n")
    with (
        patch.object(
            auth_api, "get_provider_config", AsyncMock(return_value={"enabled": True, "issuer": "i", "client_id": "c"})
        ),
        patch.object(auth_api, "verify_state_cookie", return_value=flow),
        patch.object(auth_api, "exchange_code_for_tokens", side_effect=ConnectionError("https://idp/token?secret=abc")),
    ):
        with pytest.raises(HTTPException):
            await auth_api.oidc_callback(_request(), code="c", state="s", db=AsyncMock())
    call = _only_call(recorded)
    assert call["reason_detail"] == "ConnectionError"
    assert "secret" not in str(call)
