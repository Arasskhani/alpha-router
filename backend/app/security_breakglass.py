"""Break-glass CLI for admin IP restriction lockouts."""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal, engine
from app.models.system import SystemSetting
from app.services.admin_ip_allowlist_service import (
    KEY_MODE,
    AllowlistError,
    add_entry,
    invalidate_restriction_cache,
)


async def _set_mode_off() -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(SystemSetting, KEY_MODE)
        if row:
            row.value = "off"
        else:
            db.add(SystemSetting(key=KEY_MODE, value="off"))
        await db.commit()
    invalidate_restriction_cache()
    print("Admin IP restriction mode set to off.")


async def _add_cidr(cidr: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            entry = await add_entry(db, cidr=cidr, label="break-glass", created_by_user_id=None)
        except AllowlistError as exc:
            print(str(exc), file=sys.stderr)
            await db.rollback()
            raise SystemExit(1) from exc
        await db.commit()
    print(f"Added allowlist entry {entry['cidr']} (id={entry['id']}).")


async def _show() -> None:
    async with AsyncSessionLocal() as db:
        mode_row = await db.get(SystemSetting, KEY_MODE)
        print(f"mode={mode_row.value if mode_row else 'off'}")
        from app.models.security import AdminIpAllowlistEntry

        rows = (await db.execute(select(AdminIpAllowlistEntry))).scalars().all()
        if not rows:
            print("entries=(none)")
            return
        for row in rows:
            print(f"{row.id}\t{row.cidr}\tenabled={row.enabled}\t{row.label or ''}")


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.disable_admin_ip_restriction:
            await _set_mode_off()
        if args.add_cidr:
            await _add_cidr(args.add_cidr)
        if args.show or (not args.disable_admin_ip_restriction and not args.add_cidr):
            await _show()
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear or repair admin IP restrictions.")
    parser.add_argument(
        "--disable-admin-ip-restriction",
        action="store_true",
        help="Set restriction mode to off.",
    )
    parser.add_argument("--add-cidr", help="Add an IP or CIDR to the allowlist.")
    parser.add_argument("--show", action="store_true", help="Print the current allowlist.")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
