"""Unit tests for LDAP username / display-name mapping."""

from types import SimpleNamespace

from app.services.ldap_auth import _attr_str, _entry_to_profile, _resolve_username


class _CaseEntry:
    """Simulates WinLdap entries where attribute casing may differ."""

    def __init__(self, dn: str, attrs: dict[str, str]):
        self.entry_dn = dn
        self._attrs = attrs

    @property
    def entry_attributes(self):
        return list(self._attrs.keys())

    def __getitem__(self, name: str):
        return self._attrs[name]


def test_resolve_username_prefers_sam_over_cn():
    entry = _CaseEntry(
        "CN=John Doe,DC=corp,DC=local",
        {
            "sAMAccountName": "jdoe",
            "cn": "John Doe",
            "displayName": "John Doe",
            "userPrincipalName": "jdoe@corp.local",
        },
    )
    assert _resolve_username(entry) == "jdoe"


def test_resolve_username_uses_upn_before_cn():
    entry = _CaseEntry(
        "CN=John Doe,DC=corp,DC=local",
        {
            "cn": "John Doe",
            "displayName": "John Doe",
            "userPrincipalName": "jdoe@corp.local",
        },
    )
    assert _resolve_username(entry) == "jdoe"


def test_resolve_username_case_insensitive_sam():
    entry = _CaseEntry(
        "CN=Admin,DC=corp,DC=local",
        {
            "samaccountname": "Administrator",
            "cn": "Administrator",
            "displayName": "Built-in account",
        },
    )
    assert _resolve_username(entry) == "Administrator"


def test_entry_to_profile_keeps_display_name_separate():
    entry = _CaseEntry(
        "CN=John Doe,DC=corp,DC=local",
        {
            "sAMAccountName": "jdoe",
            "cn": "John Doe",
            "displayName": "John Doe",
            "mail": "jdoe@corp.local",
        },
    )
    profile = _entry_to_profile(entry, "fallback")
    assert profile["username"] == "jdoe"
    assert profile["display_name"] == "John Doe"
    assert profile["email"] == "jdoe@corp.local"


def test_attr_str_reads_ldap3_like_attribute():
    entry = SimpleNamespace(
        entry_attributes=["sAMAccountName"],
        sAMAccountName=SimpleNamespace(values=["jdoe"]),
    )
    assert _attr_str(entry, "sAMAccountName") == "jdoe"
