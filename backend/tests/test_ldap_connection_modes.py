"""LDAP connection mode ordering for Active Directory (LDAPS-only)."""

from app.services.ldap_auth import ldap_connection_modes


def test_port_389_legacy_input_still_uses_ldaps_only():
    modes = ldap_connection_modes({"port": 389, "use_ssl": False})
    assert modes == [(636, True, False)]


def test_port_636_ldaps_only():
    modes = ldap_connection_modes({"port": 636, "use_ssl": True})
    assert modes == [(636, True, False)]


def test_use_ssl_flag_on_389_upgrades_modes():
    modes = ldap_connection_modes({"port": 389, "use_ssl": True})
    assert modes == [(636, True, False)]
