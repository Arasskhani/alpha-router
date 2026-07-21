"""LDAP sync OU prune configuration and LDAPS-only public view."""

from app.services.ldap_auth import _group_search_bases, _sync_search_bases
from app.services.ldap_config import LDAPS_PORT, expand_ldap_config, merge_simple_ldap_config, simple_public_view


def test_group_search_bases_follow_sync_ous_without_prune():
    cfg = {
        "sync_ous": ["OU=App,DC=example,DC=com"],
        "sync_ous_prune": False,
        "base_dn": "DC=example,DC=com",
        "group_base_dn": "DC=example,DC=com",
    }
    assert _group_search_bases(cfg) == ["OU=App,DC=example,DC=com"]
    assert _group_search_bases(cfg) == _sync_search_bases(cfg)


def test_group_search_bases_fall_back_to_domain_when_ous_empty():
    cfg = {
        "sync_ous": [],
        "sync_ous_prune": False,
        "base_dn": "DC=example,DC=com",
        "group_base_dn": "DC=example,DC=com",
    }
    assert _group_search_bases(cfg) == ["DC=example,DC=com"]


def test_simple_public_view_includes_sync_ous_prune():
    cfg = {
        "enabled": True,
        "dc_host": "dc.example.com",
        "bind_username": "svc",
        "bind_password": "secret",
        "port": 389,
        "use_ssl": False,
        "sync_ous_prune": True,
    }
    view = simple_public_view(cfg)
    assert view["sync_ous_prune"] is True
    assert view["port"] == LDAPS_PORT
    assert view["use_ssl"] is True


def test_merge_simple_ldap_config_forces_ldaps():
    merged = merge_simple_ldap_config(
        True,
        "dc.example.com",
        "svc",
        "secret",
        389,
        use_ssl=False,
        sync_ous_prune=True,
    )
    assert merged["sync_ous_prune"] is True
    assert merged["port"] == LDAPS_PORT
    assert merged["use_ssl"] is True
    assert merged["server"].startswith("ldaps://")
    expanded = expand_ldap_config(merged)
    assert expanded["port"] == LDAPS_PORT
    assert expanded["use_ssl"] is True
    assert expanded["sync_ous_prune"] is True
