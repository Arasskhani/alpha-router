"""End-to-end migration gate for a fresh and already-upgraded database."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import Column, Index, MetaData, String, Table

from app.db_migrate import _ensure_missing_indexes


def _run_migrate(database_path: Path) -> subprocess.CompletedProcess[str]:
    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    env.pop("ALEMBIC_AGENT_PLATFORM_ONLY", None)
    return subprocess.run(
        [sys.executable, "-m", "app.migrate"],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_agent_platform_migration_is_complete_and_idempotent():
    database_path = (
        Path(__file__).resolve().parent / f".agent-platform-{uuid.uuid4().hex}.sqlite"
    )
    try:
        _run_migrate(database_path)
        _run_migrate(database_path)

        connection = sqlite3.connect(database_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
        finally:
            connection.close()

        assert revision == ("f2a8c5d91b34",)
        assert {
            "users",
            "chat_sessions",
            "agents",
            "agent_versions",
            "agent_tools",
            "agent_tool_versions",
            "agent_tool_audit_events",
            "agent_runs",
            "agent_retrieval_traces",
            "agent_citations",
            "agent_tool_runs",
            "agent_escalation_cases",
            "governance_audit_events",
            "evaluation_datasets",
            "evaluation_cases",
            "evaluation_runs",
            "evaluation_results",
            "knowledge_bases",
            "knowledge_document_versions",
            "knowledge_chunks",
            "knowledge_index_versions",
            "ingestion_jobs",
            "outbox_events",
        }.issubset(tables)
    finally:
        database_path.unlink(missing_ok=True)


def test_legacy_schema_does_not_create_indexes_before_versioned_columns():
    metadata = MetaData()
    table = Table(
        "chat_sessions",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("current_agent_id", String(36)),
        Index("ix_chat_sessions_current_agent_id", "current_agent_id"),
    )
    connection = Mock()
    inspector = Mock()
    inspector.get_indexes.return_value = []

    _ensure_missing_indexes(
        connection,
        table,
        inspector,
        available_columns={"id"},
    )

    connection.execute.assert_not_called()
