"""Schema ownership boundaries during the transition to versioned migrations."""

from __future__ import annotations

AGENT_PLATFORM_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "agents",
        "agent_versions",
        "agent_access_assignments",
        "agent_knowledge_bindings",
        "agent_handoff_events",
        "agent_audit_events",
        "agent_tools",
        "agent_tool_versions",
        "agent_tool_audit_events",
        "agent_runs",
        "agent_retrieval_traces",
        "agent_citations",
        "agent_tool_runs",
        "agent_escalation_cases",
        "knowledge_bases",
        "knowledge_base_access_assignments",
        "knowledge_documents",
        "knowledge_document_access_assignments",
        "knowledge_document_versions",
        "knowledge_releases",
        "knowledge_release_documents",
        "knowledge_chunks",
        "knowledge_index_versions",
        "knowledge_connectors",
        "connector_sync_runs",
        "ingestion_jobs",
        "outbox_events",
        "deletion_tombstones",
        "evaluation_datasets",
        "evaluation_cases",
        "evaluation_runs",
        "evaluation_results",
        "legal_holds",
        "governance_audit_events",
        "knowledge_audit_events",
        "projects",
        "project_members",
        "project_invitations",
        "project_config_versions",
        "project_memories",
        "project_memory_grants",
        "project_memory_jobs",
        "project_memory_events",
        "project_memory_suppressions",
        "project_chat_pins",
        "project_user_prefs",
        "project_chat_composer_prefs",
        "project_audit_events",
        "project_resources",
        "project_media_assets",
        "project_room_handoffs",
        "user_memory_jobs",
        "user_memory_events",
        "user_memory_suppressions",
        "admin_ip_allowlist_entries",
        "tls_certificates",
        "security_audit_events",
        "auth_events",
    }
)


def legacy_metadata_tables(metadata) -> list:
    """Tables still bootstrapped by the legacy create-all compatibility path."""

    return [table for table in metadata.sorted_tables if table.name not in AGENT_PLATFORM_TABLE_NAMES]
