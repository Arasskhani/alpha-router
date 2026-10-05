"""The directory lookup behind email sign-up: whether a name would sign in as a directory account."""

from __future__ import annotations

import ldap3
import pytest

from app.services import ldap_auth


@pytest.fixture
def directory(monkeypatch):
    server = ldap3.Server("fake-dc")
    conn = ldap3.Connection(server, user="cn=svc,dc=example,dc=com", password="x", client_strategy=ldap3.MOCK_SYNC)
    conn.strategy.add_entry("cn=svc,dc=example,dc=com", {"userPassword": "x", "objectClass": "person"})
    conn.strategy.add_entry(
        "cn=John Doe,ou=Staff,dc=example,dc=com",
        {"objectClass": "person", "sAMAccountName": "jdoe", "userPrincipalName": "jdoe@example.com"},
    )
    conn.strategy.add_entry(
        "cn=Mary Major,ou=Elsewhere,dc=example,dc=com",
        {"objectClass": "person", "mail": "mmajor@example.com"},
    )
    conn.bind()
    monkeypatch.setattr(ldap_auth, "_open_connection", lambda _cfg, **_kw: conn)
    return {"enabled": True, "base_dn": "dc=example,dc=com", "sync_ous": "ou=Staff,dc=example,dc=com"}


def test_a_logon_name_is_found(directory):
    assert ldap_auth.ldap_username_exists("jdoe", directory) is True


def test_the_name_of_a_mail_address_outside_the_sync_ous_is_found(directory):
    assert ldap_auth.ldap_username_exists("mmajor", directory) is True


def test_a_name_nobody_has_is_free(directory):
    assert ldap_auth.ldap_username_exists("brand.new", directory) is False
