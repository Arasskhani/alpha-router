"""Carry sign-in history from security_audit_events into auth_events. Run once.

The image ships ``app/`` and not ``scripts/``, so this is a module:

    docker compose exec -T alpha-router python -m app.backfill_auth_events
    docker compose exec -T alpha-router python -m app.backfill_auth_events --dry-run

Idempotent: a second run reports everything as already carried. Safe while
the application is serving traffic. See ``app.services.auth_events_backfill``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import app.models  # noqa: F401
from app.database import AsyncSessionLocal, engine
from app.services.auth_events_backfill import backfill_auth_events, legacy_event_count, record_backfill_run


async def _run(dry_run: bool) -> int:
    try:
        async with AsyncSessionLocal() as db:
            total = await legacy_event_count(db)
            print(f"[backfill] legacy sign-in events in security_audit_events: {total}", flush=True)
            if dry_run:
                print("[backfill] dry run; nothing written.", flush=True)
                return 0
            report = await backfill_auth_events(db)
            await record_backfill_run(db, report)
            print(
                f"[backfill] scanned={report.scanned} written={report.written} "
                f"already={report.skipped_existing} redacted={report.redacted} "
                f"by_type={report.by_type} range={report.first}..{report.last}",
                flush=True,
            )
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count what would be carried, write nothing")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.dry_run)))


if __name__ == "__main__":
    main()
