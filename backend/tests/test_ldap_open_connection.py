"""LDAP multi-mode connection fallback."""

from unittest.mock import patch

import pytest

from app.services.ldap_auth import LdapUnavailableError, _is_tls_error, _open_connection_ldap3


def _cfg() -> dict:
    return {
        "enabled": True,
        "dc_host": "dc.example.com",
        "bind_username": "EXAMPLE\\svc",
        "bind_password": "secret",
        "port": 389,
        "domain": "example.com",
        "base_dn": "DC=example,DC=com",
    }


def test_starttls_used_when_available():
    calls: list[tuple[int, bool, bool]] = []

    def fake_bind(host, port, user, password, domain="", *, use_ssl=False, use_starttls=False, cfg=None):
        calls.append((port, use_ssl, use_starttls))
        if use_starttls:
            return object(), "LDAP + STARTTLS"
        raise RuntimeError("skip")

    with patch("app.services.ldap_auth._try_bind_ad", side_effect=fake_bind):
        conn = _open_connection_ldap3(_cfg())

    assert conn is not None
    assert calls[0] == (389, False, True)


def test_ssl_errors_are_not_unreachable():
    assert _is_tls_error(RuntimeError("socket ssl wrapping error: EOF"))
    assert not _is_tls_error(ConnectionRefusedError("connection refused"))


def test_all_modes_unreachable_raises_unavailable():
    def fake_bind(*_args, **_kwargs):
        raise ConnectionRefusedError("connection refused")

    with patch("app.services.ldap_auth._try_bind_ad", side_effect=fake_bind):
        with pytest.raises(LdapUnavailableError):
            _open_connection_ldap3(_cfg())
