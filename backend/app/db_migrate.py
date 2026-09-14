"""Schema synchronization for PostgreSQL production and SQLite tests."""

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex

from app.config import get_settings
from app.database import Base, engine
from app.schema_registry import AGENT_PLATFORM_TABLE_NAMES


def _ensure_missing_indexes(
    connection,
    table,
    inspector,
    *,
    available_columns: set[str],
) -> None:
    """Create ORM indexes whose backing columns already exist.

    Columns owned by Alembic may be absent while the legacy schema bootstrap
    runs, so their indexes must be deferred to the versioned migration.
    """
    existing = {index["name"] for index in inspector.get_indexes(table.name) if index.get("name")}
    for index in table.indexes:
        if not index.name or index.name in existing:
            continue
        if any(column.name not in available_columns for column in index.columns):
            continue
        connection.execute(CreateIndex(index))


async def apply_schema_column_patches() -> None:
    """Add ORM columns/indexes and drop retired columns missing from current schema.

    Multiple workers serialize discovery and DDL with a PostgreSQL advisory
    lock.  Duplicate-column errors are tolerated only for the race where
    another worker completed the same patch first.
    """
    # Columns removed from the ORM that should be dropped from existing DBs.
    # Safe when empty/greenfield; roles live only in ``user_role_assignments``.
    retired_columns: dict[str, frozenset[str]] = {
        "users": frozenset({"role"}),
    }
    versioned_columns: dict[str, frozenset[str]] = {
        "chat_sessions": frozenset(
            {
                "current_agent_id",
                "current_agent_version_id",
                "agent_selected_at",
                "project_id",
                "created_by_user_id",
                "channel_kind",
            }
        ),
        "chat_messages": frozenset({"agent_run_id", "author_display_name"}),
        "image_generation_attempts": frozenset({"project_id"}),
        "video_generation_jobs": frozenset({"project_id"}),
        "project_config_versions": frozenset({"memory_auto_capture"}),
        "project_memories": frozenset(
            {
                "category",
                "sensitivity",
                "confidence",
                "salience",
                "expires_at",
                "last_used_at",
                "use_count",
                "source_session_id",
                "source_message_id",
                "supersedes_id",
                "embedding_status",
                "embedding_model",
                "embedding_dims",
                "indexed_at",
                "deleted_at",
            }
        ),
        "user_memories": frozenset(
            {
                "origin",
                "category",
                "sensitivity",
                "confidence",
                "salience",
                "expires_at",
                "last_used_at",
                "use_count",
                "source_message_id",
                "supersedes_id",
                "embedding_status",
                "embedding_model",
                "embedding_dims",
                "indexed_at",
                "deleted_at",
            }
        ),
    }
    # Tables removed from the ORM (feature retired).
    retired_tables: frozenset[str] = frozenset({"user_connectors"})

    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(56023113)"))

        def patch(connection) -> None:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            for retired_table in retired_tables:
                if retired_table not in tables:
                    continue
                try:
                    connection.execute(text(f"DROP TABLE IF EXISTS {retired_table} CASCADE"))
                except Exception as exc:
                    message = str(exc).lower()
                    if "does not exist" in message or "no such table" in message:
                        continue
                    raise
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            for table in Base.metadata.sorted_tables:
                if table.name in AGENT_PLATFORM_TABLE_NAMES:
                    continue
                if table.name not in tables:
                    continue
                existing = {column["name"] for column in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in versioned_columns.get(table.name, ()):
                        continue
                    if column.name in existing:
                        continue
                    ddl = column.type.compile(dialect=connection.dialect)
                    try:
                        connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl}"))
                        existing.add(column.name)
                    except Exception as exc:
                        message = str(exc).lower()
                        if "already exists" in message or "duplicate column" in message:
                            existing.add(column.name)
                            continue
                        raise
                for retired in retired_columns.get(table.name, ()):
                    if retired not in existing:
                        continue
                    try:
                        connection.execute(text(f"ALTER TABLE {table.name} DROP COLUMN {retired}"))
                        existing.discard(retired)
                    except Exception as exc:
                        message = str(exc).lower()
                        if "does not exist" in message or "no such column" in message:
                            existing.discard(retired)
                            continue
                        raise
                _ensure_missing_indexes(
                    connection,
                    table,
                    inspector,
                    available_columns=existing,
                )

        await conn.run_sync(patch)


async def backfill_api_key_unlimited_budget() -> None:
    """One-time data migration for ``alpha_router_api_keys.unlimited_budget``.

    Before this column existed, ``credit_limit_usd <= 0`` meant "no cap". To
    keep every existing key working exactly as before, rows that still have
    NULL in the new column get ``true`` when they had no positive limit and
    ``false`` otherwise. New keys always carry an explicit value, so this
    touches nothing after the first run. Admins should review the keys now
    flagged unlimited (the UI marks them).
    """
    async with engine.begin() as conn:
        try:
            await conn.execute(
                text(
                    "UPDATE alpha_router_api_keys SET unlimited_budget = "
                    "CASE WHEN credit_limit_usd IS NULL OR credit_limit_usd <= 0 "
                    "THEN TRUE ELSE FALSE END WHERE unlimited_budget IS NULL"
                )
            )
        except Exception as exc:
            message = str(exc).lower()
            if "does not exist" in message or "no such table" in message or "no such column" in message:
                return
            raise


async def validate_agent_platform_schema() -> None:
    """Fail startup when the versioned Agent Platform migration was not applied."""

    required = {
        "agents": {"slug", "status", "access_type", "acl_version"},
        "agent_versions": {
            "agent_id",
            "version_number",
            "fingerprint",
            "active_scope_key",
        },
        "agent_access_assignments": {"agent_id", "effect"},
        "agent_handoff_events": {
            "session_id",
            "turn_id",
            "turn_ordinal",
            "status",
            "context_payload",
        },
        "agent_tools": {"slug", "status"},
        "agent_tool_versions": {
            "tool_id",
            "version_number",
            "fingerprint",
            "active_scope_key",
            "input_schema",
            "output_schema",
            "handler_key",
            "effect_type",
            "approval_mode",
            "last_modified_by_user_id",
            "submitted_by_user_id",
        },
        "agent_tool_audit_events": {"tool_id", "event_type", "created_at"},
        "agent_runs": {
            "correlation_id",
            "agent_version_id",
            "routing_outcome",
            "retrieval_outcome",
            "guardrail_events",
            "egress_manifest",
            "total_cost_usd",
            "private_mode",
        },
        "agent_retrieval_traces": {
            "agent_run_id",
            "query_sha256",
            "outcome",
            "results",
        },
        "agent_citations": {
            "agent_run_id",
            "citation_id",
            "document_version_id",
        },
        "agent_tool_runs": {
            "agent_run_id",
            "tool_version_id",
            "arguments_sha256",
            "status",
        },
        "agent_escalation_cases": {"agent_run_id", "status", "reason_code"},
        "chat_sessions": {
            "current_agent_id",
            "current_agent_version_id",
            "agent_selected_at",
            "channel_kind",
        },
        "project_room_handoffs": {
            "source_session_id",
            "target_session_id",
            "brief",
            "created_by_user_id",
        },
        "chat_messages": {"agent_run_id"},
        "knowledge_bases": {"slug", "sensitivity", "access_type", "acl_version"},
        "knowledge_documents": {"knowledge_base_id", "canonical_key", "status"},
        "knowledge_document_versions": {"document_id", "sha256", "storage_key"},
        "knowledge_releases": {"knowledge_base_id", "fingerprint", "active_scope_key"},
        "knowledge_chunks": {"document_version_id", "content_hash", "content"},
        "knowledge_index_versions": {
            "knowledge_base_id",
            "embedding_fingerprint",
            "collection_name",
        },
        "ingestion_jobs": {"idempotency_key", "status", "lease_until"},
        "outbox_events": {"idempotency_key", "event_type", "status"},
        "governance_audit_events": {
            "event_type",
            "resource_type",
            "payload_json",
            "previous_event_hash",
            "event_hash",
            "created_at",
        },
        "evaluation_datasets": {
            "agent_id",
            "slug",
            "version_number",
            "status",
            "thresholds_json",
            "is_publish_gate",
        },
        "evaluation_cases": {
            "dataset_id",
            "case_key",
            "category",
            "language",
            "expected_json",
        },
        "evaluation_runs": {
            "dataset_id",
            "agent_version_id",
            "dataset_snapshot_hash",
            "status",
            "metrics_json",
        },
        "evaluation_results": {
            "run_id",
            "case_id",
            "status",
            "metrics_json",
            "failure_codes_json",
        },
        "projects": {
            "name",
            "status",
            "visibility",
            "created_by_user_id",
            "active_config_version_id",
            "knowledge_base_id",
            "revision",
            "acl_version",
        },
        "project_members": {"project_id", "user_id", "role"},
        "project_invitations": {
            "project_id",
            "role",
            "token_hash",
            "max_uses",
            "use_count",
            "expires_at",
        },
        "project_config_versions": {
            "project_id",
            "revision",
            "memory_enabled",
            "grounding_policy",
        },
        "project_memories": {
            "project_id",
            "content",
            "content_hash",
            "source_type",
            "authority",
            "enabled",
        },
        "project_memory_grants": {
            "consumer_project_id",
            "source_project_id",
            "status",
            "revision",
        },
        "project_chat_pins": {"project_id", "session_id", "pinned_by_user_id"},
        "project_chat_composer_prefs": {
            "project_id",
            "session_id",
            "user_id",
            "tools",
            "tools_touched",
        },
        "project_audit_events": {
            "event_type",
            "actor_user_id",
            "outcome",
            "payload_json",
            "created_at",
        },
        "project_resources": {
            "project_id",
            "document_id",
            "title",
            "status",
            "uploaded_by_user_id",
            "created_at",
            "updated_at",
        },
        "user_memories": {
            "origin",
            "category",
            "sensitivity",
            "salience",
            "embedding_status",
            "content_hash",
        },
        "user_memory_jobs": {
            "user_id",
            "session_id",
            "status",
            "watermark_sequence",
            "extracted_sequence",
            "run_after",
        },
        "user_memory_events": {
            "user_id",
            "event_type",
            "actor",
            "created_at",
        },
        "user_memory_suppressions": {
            "user_id",
            "content_hash",
        },
    }

    async with engine.connect() as conn:

        def validate(connection) -> list[str]:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            missing: list[str] = []
            for table_name, expected_columns in required.items():
                if table_name not in tables:
                    missing.append(f"table:{table_name}")
                    continue
                present = {column["name"] for column in inspector.get_columns(table_name)}
                missing.extend(f"column:{table_name}.{column}" for column in sorted(expected_columns - present))
            return missing

        missing = await conn.run_sync(validate)
    if missing:
        raise RuntimeError(
            "Agent Platform schema is incomplete; run `python -m app.migrate` "
            "before starting Alpharouter. Missing: " + ", ".join(missing)
        )


async def validate_accounting_schema() -> None:
    """Fail readiness when required accounting storage is incomplete."""

    required = {
        "pricing_snapshots": {
            "provider_type",
            "service_type",
            "active_scope_key",
            "pricing_json",
        },
        "usage_operations": {
            "idempotency_key",
            "accounting_status",
            "total_cost_usd",
        },
        "usage_events": {
            "operation_id",
            "final_cost_usd",
            "cost_source",
            "cost_confidence",
            "reconciliation_attempts",
        },
        "cost_line_items": {"usage_event_id", "quantity", "unit", "cost_usd"},
        "cost_ledger_entries": {
            "operation_id",
            "amount_usd",
            "idempotency_key",
            "effective_at",
        },
        "reconciliation_runs": {"provider_type", "status", "adjustment_usd"},
        "request_logs": {
            "usage_operation_id",
            "cost_source",
            "cost_confidence",
            "has_unpriced_usage",
            "project_id",
        },
    }

    async with engine.connect() as conn:

        def validate(connection) -> list[str]:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            missing: list[str] = []
            for table_name, expected_columns in required.items():
                if table_name not in tables:
                    missing.append(f"table:{table_name}")
                    continue
                present = {column["name"] for column in inspector.get_columns(table_name)}
                missing.extend(f"column:{table_name}.{column}" for column in sorted(expected_columns - present))
            return missing

        missing = await conn.run_sync(validate)
    if missing:
        raise RuntimeError("Accounting schema is incomplete: " + ", ".join(missing))


async def apply_sqlite_schema_patches() -> None:
    """Apply current-schema patches only for a configured SQLite database."""
    if "sqlite" not in get_settings().database_url:
        return
    await apply_schema_column_patches()
