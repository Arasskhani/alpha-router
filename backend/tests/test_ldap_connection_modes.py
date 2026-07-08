"""LDAP connection mode ordering for Active Directory."""

from app.services.ldap_auth import ldap_connection_modes


def test_port_389_prefers_starttls_then_plain_then_ldaps():
    modes = ldap_connection_modes({"port": 389, "use_ssl": False})
    assert modes[0] == (389, False, True)
    assert (389, False, False) in modes
    assert (636, True, False) in modes
    assert modes.index((389, False, True)) < modes.index((389, False, False))
    assert modes.index((389, False, False)) < modes.index((636, True, False))


def test_port_636_ldaps_only():
    modes = ldap_connection_modes({"port": 636, "use_ssl": True})
    assert modes == [(636, True, False)]


def test_use_ssl_flag_on_389_upgrades_modes():
    modes = ldap_connection_modes({"port": 389, "use_ssl": True})
    assert modes == [(636, True, False)]
