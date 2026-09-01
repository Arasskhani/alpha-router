from app.schema_registry import AGENT_PLATFORM_TABLE_NAMES


def test_security_tables_are_alembic_owned():
    assert "admin_ip_allowlist_entries" in AGENT_PLATFORM_TABLE_NAMES
    assert "tls_certificates" in AGENT_PLATFORM_TABLE_NAMES
    assert "security_audit_events" in AGENT_PLATFORM_TABLE_NAMES
