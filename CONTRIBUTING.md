# Contributing to Alpharouter

This file is the short version of how a change gets from a working tree into
`main`. Everything here is enforced by CI (`.gitlab-ci.yml`) and, locally, by
the pre-commit hooks — the text explains *why* each gate exists so you can
work with it instead of around it.

## One-time setup

```bash
# Backend tooling (same pins as CI)
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.lock -r backend/requirements-dev.txt

# Frontend tooling
cd frontend && npm ci && cd ..

# Commit hooks: lint/format/type/dead-code on pre-commit, message format on commit-msg
pip install pre-commit
pre-commit install --install-hooks -t pre-commit -t commit-msg
```

## Branches and merge requests

- `main` is protected. Work on `fix/…`, `feat/…`, `chore/…`, `refactor/…`.
- One concern per commit and per MR. "Update3" style commits are rejected by
  the commit-msg hook.
- An MR touching money (`budget_*`, `usage_accounting_*`, `proxy_service`
  settlement), auth (SAML/OIDC/LDAP/CSRF), chat sync or the scheduler is not
  mergeable without a test, and the money path must also be covered by the
  Postgres canary (`tests/test_budget_reservations_postgres.py` or a sibling
  run under `RUN_POSTGRES_RESERVATION_CANARY=1`) — SQLite ignores
  `FOR UPDATE`.
- Fix the cause, do not add a second guard, unless the commit says
  "defense-in-depth" and why.

## Commit messages — Conventional Commits

```
<type>(<scope>): <description>          # <= 100 chars, lowercase start, no period

<body: the bug, why it happens, what changes in behaviour, how it was tested>
```

`type` is one of `build chore ci docs feat fix perf refactor revert style test`;
`scope` is optional (`budget`, `chat`, `frontend`, `ops`, …); `!` after the
type/scope marks a breaking change. `scripts/check-commit-message.py` is the
hook; `scripts/tests/test-commit-message.sh` shows what passes.

## The gates, and how to satisfy them

| Gate | Command | When it fails |
|------|---------|---------------|
| ruff (lint + format) | `cd backend && ruff check . && ruff format --check .` | Run `ruff check --fix .` and `ruff format .`. Rule set: `backend/ruff.toml`. A blind `except Exception` needs `# noqa: BLE001 -- <reason>`; a function above complexity 20 needs `# noqa: C901 -- <reason>` and belongs on the Phase 4 split list. |
| mypy baseline | `scripts/mypy-check.sh` | Any error not in `backend/mypy-baseline.txt` fails. Fix it. Only after fixing *existing* errors run `scripts/mypy-check.sh --sync` so the baseline shrinks; never sync to hide a new error. |
| vulture | `cd backend && vulture app vulture_whitelist.py --min-confidence 80` | Delete the dead code. Names used only dynamically go in `vulture_whitelist.py` with a reason. |
| pytest (SQLite) | `cd backend && pytest -q` | Tests are `async def`; use the fixtures in `tests/conftest.py` (`db_session`, `client`, `user`, `admin`). No new `asyncio.run` or `create_async_engine` in tests. |
| Postgres canary | see `backend-postgres-canary` in CI | Reproduce with a local Postgres: `DATABASE_URL=postgresql+asyncpg://… RUN_POSTGRES_RESERVATION_CANARY=1 pytest tests/test_budget_reservations_postgres.py …`. |
| eslint | `cd frontend && npm run lint` | Errors fail; the warning budget (`--max-warnings` in `package.json`) may only go down. Fix a few warnings and lower it. |
| tsc / vitest / build | `npm run typecheck && npm test && npm run build` | Types first, then behaviour, then the bundle. |
| knip | `cd frontend && npm run knip` | Remove the unused export/type/dependency, or use it. Do not add it to an ignore list. |
| frontend sources | `bash scripts/check-frontend-sources.sh` | Never commit compiled `.js` next to `.ts/.tsx` — Vite would bundle the stale copy. |
| shell harnesses | `for t in scripts/tests/test-*.sh; do bash "$t"; done` | Install/upgrade scripts are tested with mocked docker; keep it that way. |
| dependency audit | `pip-audit`, `npm audit`, Trivy on images | Bump the dependency. Runtime Python versions live in `backend/requirements.lock` (hashed, regenerated with `uv pip compile`, see the file header); direct dependencies in `requirements.txt`. |

## Dependencies

- Python runtime: edit `backend/requirements.txt`, regenerate
  `backend/requirements.lock` (command in its header), commit both. The Docker
  image and CI install only from the lock.
- Python tooling: `backend/requirements-dev.txt`, exact pins.
- Sandbox / broker images: `sandbox/requirements.in` →
  `sandbox/requirements.txt` (same for `sandbox-broker/`).
- Frontend: `npm install <pkg>` updates `package-lock.json`; CI uses `npm ci`.
- Renovate (`renovate.json`) opens weekly update MRs and pins base-image digests.

## Where things are

- `backend/app/core/` — dependency-free helpers shared by models, services and
  API (`constants.py`, `prompt_fences.py`, `redis_client.py`, …). Never import
  `app.services` from here.
- `backend/app/services/system_default_models.py` — the only owner of the
  admin "system default model" settings, per capability.
- `scripts/codemods/` — one-shot refactors kept for reference; not run in CI.
- Persian-facing UI text lives in the frontend; backend messages are English.

## Before you push

```bash
pre-commit run --all-files        # what the hooks would do
cd backend && pytest -q && cd ..
cd frontend && npm run lint && npm run knip && npm test && npm run build
```
