"""LDAP sync OU prune configuration."""

from app.services.ldap_config import expand_ldap_config, merge_simple_ldap_config, simple_public_view


def test_simple_public_view_includes_sync_ous_prune():
    cfg = {
        "enabled": True,
        "dc_host": "dc.example.com",
        "bind_username": "svc",
        "bind_password": "secret",
        "port": 389,
        "sync_ous_prune": True,
    }
    view = simple_public_view(cfg)
    assert view["sync_ous_prune"] is True


def test_merge_simple_ldap_config_persists_sync_ous_prune():
    merged = merge_simple_ldap_config(
        True,
        "dc.example.com",
        "svc",
        "secret",
        389,
        sync_ous_prune=True,
    )
    assert merged["sync_ous_prune"] is True
    expanded = expand_ldap_config(merged)
    assert expanded["sync_ous_prune"] is True
