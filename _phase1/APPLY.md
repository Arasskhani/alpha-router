# Alpharouter — Phase 1 (Stop the bleeding) — applying the changes

Branch: `fix/phase1-stop-the-bleeding` (10 commits) on top of `fix/phase0-ci-trust` (`1ac8ada`).
Head: `6d499da`.

Prerequisite: `fix/phase0-ci-trust` must already exist locally at `1ac8ada`
(applied from `_phase0`). Check with `git rev-parse --short fix/phase0-ci-trust`.

## Option A — git bundle (recommended)

```powershell
cd C:\APPS\alpha-router
git bundle verify _phase1\alpharouter-phase1.bundle
git fetch _phase1\alpharouter-phase1.bundle fix/phase1-stop-the-bleeding:fix/phase1-stop-the-bleeding
git checkout fix/phase1-stop-the-bleeding
git log --oneline fix/phase0-ci-trust..HEAD      # 10 commits expected
```

## Option B — patches

```powershell
cd C:\APPS\alpha-router
git checkout -b fix/phase1-stop-the-bleeding fix/phase0-ci-trust
git am --3way _phase1\patches\*.patch
```

## Commits

| # | Commit | Step | Scope |
|---|--------|------|-------|
| 1 | f3deaa3 | 1.1 | Stream cancellation settles usage/budget; upstream closed on Stop; `GeneratorExit` handled |
| 2 | b05bedf | 1.2 | LDAP sync can no longer take over password-bearing local accounts; TOTP per account; `scripts/audit-ldap-relinks.py` |
| 3 | cef8430 | 1.3 | `POSTGRES_PASSWORD` rotation now applied in the cluster (`ALTER ROLE`) or refused |
| 4 | 9f89a2b | 1.4 | `scripts/backup.sh`, `scripts/restore.sh`, pre-upgrade snapshot + `:prev` image tags |
| 5 | 1e26010 | 1.5 | Scheduler leader election (advisory lock 56023115) — one APScheduler per deployment |
| 6 | 301d5dd | 1.6 | `GET /ready`, compose healthcheck/restart policies, graceful shutdown 110s |
| 7 | cafdaf8 | 1.7 | JSON body ceiling (`MAX_JSON_BODY_BYTES`, 8 MiB) separated from upload ceiling; nginx mirrors it |
| 8 | d052902 | 1.8 | Stream releases its DB connection before awaiting the provider |
| 9 | 18c9375 | 1.9 | CI: Trivy scan (CRITICAL/HIGH, unfixed ignored) + CycloneDX SBOM per image |
| 10 | 6d499da | 1.7 fix | Publishing a new body ceiling invalidates the local cache (found by the full run) |

## Verification performed in the cloud workspace

- `pytest backend/tests` (Python 3.12, SQLite): **1282 passed, 4 skipped**
- Postgres 16 canary (`RUN_POSTGRES_RESERVATION_CANARY=1`): `python -m app.migrate` + `test_budget_reservations_postgres.py`, `test_scheduler_leader.py`, `test_readiness.py` — **9 passed**
- `ruff check backend` — clean
- `scripts/tests/test-backup-flow.sh` (8/8), `scripts/tests/test-deploy-mode-pg-rotation.sh` (5/5)
- Frontend not touched in this phase.

## Operator notes after deploying

1. `.env`: add `LDAP_LINK_LOCAL_PASSWORD_ACCOUNTS=false` and `MAX_JSON_BODY_BYTES=8388608` (both have safe defaults if absent).
2. Run the LDAP re-link audit once:
   `docker compose cp scripts/audit-ldap-relinks.py alpha-router:/tmp/ && docker compose exec alpha-router python /tmp/audit-ldap-relinks.py`
   Review the list; `--revert <ids>` restores affected accounts to local auth.
3. `docker compose up -d` recreates `alpha-router` (new healthcheck, `stop_grace_period`) and the edge (now waits for `service_healthy`).
4. Take a first backup: `./scripts/backup.sh --consistent`. From now on `upgrade.sh` does this automatically (`SKIP_BACKUP=1` to skip).
5. In the logs exactly one worker should print `This worker is now the scheduler leader`.
6. Push: `git push -u origin fix/phase1-stop-the-bleeding` (the cloud session has no push access to the GitLab origin).
