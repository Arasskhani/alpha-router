#!/usr/bin/env python3
"""List accounts that a directory sync converted from local to LDAP.

Between 2026-09-13 and the link-policy fix, LDAP sync re-linked *every* matched
local row -- including password-bearing administrators -- to
``auth_provider="ldap"``. Those rows are recognisable: an LDAP account never has
a locally set password, so ``auth_provider='ldap' AND hashed_password IS NOT
NULL`` is exactly the set that was flipped (plus rows an operator linked on
purpose with LDAP_LINK_LOCAL_PASSWORD_ACCOUNTS=true).

Read-only by default. The image does not ship scripts/, so copy the file into
the app container's /tmp (the only writable path) and run it there, where
DATABASE_URL and the app package resolve:

    docker compose cp scripts/audit-ldap-relinks.py alpha-router:/tmp/audit-ldap-relinks.py
    docker compose exec -T alpha-router python /tmp/audit-ldap-relinks.py
    docker compose exec -T alpha-router python /tmp/audit-ldap-relinks.py --revert 12 34

``--revert`` sets auth_provider back to ``local`` for the given user ids and
clears external_id; it never touches passwords, roles or TOTP state.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

import app.models  # noqa: F401
from app.database import AsyncSessionLocal
from app.models.user import User, UserRoleAssignment


async def _audit(revert_ids: set[int]) -> int:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(User)
                .where(User.auth_provider == "ldap", User.hashed_password.is_not(None))
                .order_by(User.id)
            )
        ).scalars().all()
        if not rows:
            print("No LDAP rows with a local password found.")
            return 0

        role_rows = (
            await db.execute(
                select(UserRoleAssignment.user_id, UserRoleAssignment.role_slug).where(
                    UserRoleAssignment.user_id.in_([u.id for u in rows])
                )
            )
        ).all()
        roles: dict[int, list[str]] = {}
        for uid, slug in role_rows:
            roles.setdefault(int(uid), []).append(str(slug))

        print(f"{'id':>6}  {'username':<32} {'totp':<5} {'deleted':<8} {'external_id':<40} roles")
        for u in rows:
            print(
                f"{u.id:>6}  {u.username:<32} {str(bool(u.totp_enabled)):<5} "
                f"{str(u.deleted_at is not None):<8} {str(u.external_id or '')[:40]:<40} "
                f"{','.join(roles.get(u.id, [])) or '-'}"
            )

        if not revert_ids:
            print(
                f"\n{len(rows)} row(s). Re-run with --revert <id> [<id> ...] to restore "
                "auth_provider=local for specific rows."
            )
            return 0

        known = {u.id: u for u in rows}
        unknown = sorted(revert_ids - set(known))
        if unknown:
            print(f"Refusing: ids not in the list above: {unknown}", file=sys.stderr)
            return 2
        for uid in sorted(revert_ids):
            u = known[uid]
            u.auth_provider = "local"
            u.external_id = None
            print(f"reverted {uid} ({u.username}) -> local")
        await db.commit()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--revert", nargs="*", type=int, default=[], metavar="USER_ID")
    args = parser.parse_args()
    return asyncio.run(_audit(set(args.revert)))


if __name__ == "__main__":
    raise SystemExit(main())
