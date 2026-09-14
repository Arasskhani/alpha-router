"""Read-only database health and table statistics (SQLite + PostgreSQL)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

# Alpharouter application tables (read-only row counts for admins).
TABLE_LABELS: list[tuple[str, str]] = [
    ("users", "Users"),
    ("user_groups", "Groups"),
    ("user_group_members", "Group membership"),
    ("connections", "Connections"),
    ("ai_models", "Models"),
    ("alpha_router_api_keys", "Gateway API keys"),
    ("alpha_router_api_key_connections", "API key allowed connections"),
    ("alpha_router_api_key_models", "API key allowed models"),
    ("alpha_router_api_key_audit_logs", "API key change log"),
    ("connection_audit_logs", "Connection change log"),
    ("user_api_keys", "User API keys"),
    ("budget_plans", "Plans"),
    ("plan_assignments", "Plan assignments"),
    ("request_logs", "API request logs"),
    ("budget_reservations", "Budget reservations"),
    ("pricing_snapshots", "Pricing snapshots"),
    ("usage_operations", "Usage operations"),
    ("usage_events", "Usage events"),
    ("cost_line_items", "Cost line items"),
    ("cost_ledger_entries", "Cost ledger entries"),
    ("reconciliation_runs", "Cost reconciliation runs"),
    ("media_assets", "Media metadata"),
    ("smtp_settings", "SMTP settings"),
    ("report_schedules", "Report schedules"),
    ("system_settings", "System settings"),
    ("auth_providers", "Auth providers"),
]


def _engine_kind(database_url: str) -> str:
    if database_url.startswith("sqlite"):
        return "sqlite"
    if "postgresql" in database_url:
        return "postgresql"
    return "other"


def _mask_database_url(database_url: str) -> str:
    """Hide credentials in connection string shown to admins."""
    if "@" in database_url and "://" in database_url:
        scheme, rest = database_url.split("://", 1)
        if "@" in rest:
            host_part = rest.split("@", 1)[1]
            return f"{scheme}://***@{host_part}"
    return database_url


def _sqlite_file_path(database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if database_url.startswith(prefix):
        raw = database_url[len(prefix) :]
        return Path(raw)
    if database_url.startswith("sqlite:///"):
        return Path(database_url.replace("sqlite:///", "", 1))
    return None


async def _ping_ms(db: AsyncSession) -> float:
    t0 = time.perf_counter()
    await db.execute(text("SELECT 1"))
    return round((time.perf_counter() - t0) * 1000, 2)


async def _table_exists(db: AsyncSession, table: str, kind: str) -> bool:
    if kind == "sqlite":
        row = (
            await db.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name LIMIT 1"),
                {"name": table},
            )
        ).first()
        return row is not None
    row = (
        await db.execute(
            text(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :name LIMIT 1"
            ),
            {"name": table},
        )
    ).first()
    return row is not None


async def _count_rows(db: AsyncSession, table: str) -> int | None:
    # Table names are fixed allowlist — safe for identifier interpolation.
    result = await db.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
    val = result.scalar()
    return int(val) if val is not None else 0


async def collect_system_metrics() -> dict[str, Any]:
    """``_collect_system_metrics`` off the event loop.

    psutil's ``cpu_percent(interval=...)`` sleeps for the sampling window
    (0.15 s + 0.1 s here). Called inline that stalled every request on the
    worker for a quarter second per admin refresh and per metrics snapshot.
    """
    return await asyncio.to_thread(_collect_system_metrics)


def _collect_system_metrics() -> dict[str, Any]:
    """Host and Alpharouter process CPU/RAM (machine or container running this API)."""
    out: dict[str, Any] = {
        "available": False,
        "host": None,
        "process": None,
        "error": None,
    }
    try:
        import psutil
    except ImportError:
        out["error"] = "psutil not installed"
        return out

    try:
        vm = psutil.virtual_memory()
        # Short sample so CPU % is meaningful on refresh.
        host_cpu = psutil.cpu_percent(interval=0.15)
        out["host"] = {
            "cpu_percent": round(host_cpu, 1),
            "memory_total_bytes": int(vm.total),
            "memory_used_bytes": int(vm.used),
            "memory_available_bytes": int(vm.available),
            "memory_percent": round(vm.percent, 1),
        }
        proc = psutil.Process(os.getpid())
        with proc.oneshot():
            mem = proc.memory_info()
            proc_cpu = proc.cpu_percent(interval=0.1)
        out["process"] = {
            "pid": proc.pid,
            "name": proc.name(),
            "cpu_percent": round(proc_cpu, 1),
            "memory_rss_bytes": int(mem.rss),
        }
        out["available"] = True
    except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
        out["error"] = str(exc)
    return out


async def collect_snapshot_metrics(db: AsyncSession) -> dict[str, Any]:
    """Lightweight metrics for hourly snapshots (no per-table counts)."""
    settings = get_settings()
    url = settings.database_url
    kind = _engine_kind(url)
    out: dict[str, Any] = {
        "db_engine": kind,
        "host_cpu_percent": None,
        "host_memory_percent": None,
        "process_cpu_percent": None,
        "process_rss_bytes": None,
        "db_ping_ms": None,
        "db_size_bytes": None,
    }
    try:
        out["db_ping_ms"] = await _ping_ms(db)
        if kind == "sqlite":
            fp = _sqlite_file_path(url)
            if fp and fp.is_file():
                out["db_size_bytes"] = fp.stat().st_size
        elif kind == "postgresql":
            size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
            out["db_size_bytes"] = int(size) if size is not None else None
    except Exception:  # noqa: BLE001 -- best-effort side effect, failure intentionally ignored (Phase 4: log at DEBUG)
        pass
    system = await collect_system_metrics()
    if system.get("available") and system.get("host"):
        out["host_cpu_percent"] = system["host"].get("cpu_percent")
        out["host_memory_percent"] = system["host"].get("memory_percent")
    if system.get("available") and system.get("process"):
        out["process_cpu_percent"] = system["process"].get("cpu_percent")
        out["process_rss_bytes"] = system["process"].get("memory_rss_bytes")
    return out


async def collect_database_monitor(db: AsyncSession) -> dict[str, Any]:
    settings = get_settings()
    url = settings.database_url
    kind = _engine_kind(url)
    out: dict[str, Any] = {
        "connected": False,
        "engine": kind,
        "database_url_masked": _mask_database_url(url),
        "ping_ms": None,
        "version": None,
        "database_name": None,
        "database_size_bytes": None,
        "database_file_path": None,
        "postgres_connections": None,
        "tables": [],
        "system": await collect_system_metrics(),
        "error": None,
    }

    try:
        out["ping_ms"] = await _ping_ms(db)
        out["connected"] = True

        if kind == "sqlite":
            ver = (await db.execute(text("SELECT sqlite_version()"))).scalar()
            out["version"] = f"SQLite {ver}"
            fp = _sqlite_file_path(url)
            if fp:
                out["database_file_path"] = str(fp.resolve())
                out["database_name"] = fp.name
                if fp.is_file():
                    out["database_size_bytes"] = fp.stat().st_size
        elif kind == "postgresql":
            ver = (await db.execute(text("SELECT version()"))).scalar()
            out["version"] = str(ver).split(",")[0] if ver else None
            db_name = (await db.execute(text("SELECT current_database()"))).scalar()
            out["database_name"] = db_name
            size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
            out["database_size_bytes"] = int(size) if size is not None else None
            conns = (
                await db.execute(
                    text(
                        "SELECT count(*)::int FROM pg_stat_activity "
                        "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                    )
                )
            ).scalar()
            out["postgres_connections"] = int(conns) if conns is not None else None
        else:
            out["error"] = f"Unsupported engine for monitoring: {kind}"

        tables_out: list[dict[str, Any]] = []
        for table_name, label in TABLE_LABELS:
            if kind not in ("sqlite", "postgresql"):
                break
            if not await _table_exists(db, table_name, kind):
                tables_out.append(
                    {
                        "name": table_name,
                        "label": label,
                        "exists": False,
                        "row_count": None,
                    }
                )
                continue
            try:
                count = await _count_rows(db, table_name)
            except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
                tables_out.append(
                    {
                        "name": table_name,
                        "label": label,
                        "exists": True,
                        "row_count": None,
                        "error": str(exc),
                    }
                )
                continue
            tables_out.append(
                {
                    "name": table_name,
                    "label": label,
                    "exists": True,
                    "row_count": count,
                }
            )
        out["tables"] = tables_out
    except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
        out["connected"] = False
        out["error"] = str(exc)

    return out
