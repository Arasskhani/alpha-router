"""LDAP DNS domain inference from AD identities."""

from app.services.ldap_auth import bind_candidates
from app.services.ldap_config import infer_domain, merge_simple_ldap_config


def test_infer_domain_from_base_dn_not_netbios():
    assert infer_domain(r"ArassTech\Administrator", "DC=ArassTech,DC=local") == "ArassTech.local"


def test_infer_domain_netbios_only_without_base():
    assert infer_domain(r"ArassTech\Administrator") == ""


def test_merge_config_prefers_rootdse_dns_domain(monkeypatch):
    monkeypatch.setattr(
        "app.services.ldap_config.discover_root_dse",
        lambda _host, _port: {"base_dn": "DC=ArassTech,DC=local", "domain": "ArassTech.local"},
    )
    cfg = merge_simple_ldap_config(
        True,
        "10.0.10.10",
        r"ArassTech\Administrator",
        "secret",
        389,
    )
    assert cfg["domain"] == "ArassTech.local"
    assert cfg["base_dn"] == "DC=ArassTech,DC=local"


def test_merge_config_uncheck_ldaps_normalizes_port(monkeypatch):
    monkeypatch.setattr(
        "app.services.ldap_config.discover_root_dse",
        lambda _host, _port: {"base_dn": "DC=corp,DC=local", "domain": "corp.local"},
    )
    cfg = merge_simple_ldap_config(
        True,
        "dc01.corp.local",
        "Administrator",
        "secret",
        636,
        use_ssl=False,
    )
    assert cfg["port"] == 389
    assert cfg["use_ssl"] is False
    assert cfg["server"] == "ldap://dc01.corp.local:389"


def test_merge_config_ldaps_port_forces_ssl(monkeypatch):
    monkeypatch.setattr(
        "app.services.ldap_config.discover_root_dse",
        lambda _host, _port: {"base_dn": "DC=corp,DC=local", "domain": "corp.local"},
    )
    cfg = merge_simple_ldap_config(
        True,
        "dc01.corp.local",
        "Administrator",
        "secret",
        636,
        use_ssl=True,
    )
    assert cfg["port"] == 636
    assert cfg["use_ssl"] is True
    assert cfg["server"] == "ldaps://dc01.corp.local:636"


def test_bind_candidates_upn_uses_sam_not_domain_user():
    cfg = {
        "bind_username": r"ArassTech\Administrator",
        "domain": "ArassTech.local",
        "base_dn": "DC=ArassTech,DC=local",
    }
    candidates = bind_candidates(cfg)
    assert "Administrator@ArassTech.local" in candidates
    assert "Administrator" in candidates
    assert "ArassTech\\Administrator@ArassTech.local" not in candidates


def test_bind_candidates_short_username_adds_domain_forms():
    cfg = {
        "bind_username": "Administrator",
        "domain": "ArassTech.local",
        "base_dn": "DC=ArassTech,DC=local",
    }
    candidates = bind_candidates(cfg)
    assert "Administrator" in candidates
    assert "ArassTech\\Administrator" in candidates
    assert "Administrator@ArassTech.local" in candidates
