# Contributing to Alpharouter

This file is the short version of how a change gets from a working tree into
`main`. Everything here is enforced by CI (`.gitlab-ci.yml`) and, locally, by
the pre-commit hooks — the text explains *why* each gate exists so you can
work with it instead of around it.

## One-time setup

```bash
# Backend tooling (same pins as CI)
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r backend/requirements.lock
pip install --require-hashes -r backend/requirements-dev.txt

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

These subjects are also the release notes, so write the description for
somebody reading the release page rather than the diff. A `!` or a
`BREAKING CHANGE:` body line puts the commit at the top of the notes, and the
scopes `security`, `rbac`, `audit` and `auth` move a `feat`/`fix` into the
"Security & hardening" section.

## Releasing

Tagging is the whole release. The tag decides which code a host deploys
(`latest_release_tag`), what the product reports as its version
(`resolve_app_version`, stamped into the image at build time), and — via
`.github/workflows/release.yml` — the GitHub Release notes. There is no version
file to bump and no changelog to edit.

```bash
git push origin main
git tag -a v1.2.3 -m "<a short title>"
git push origin v1.2.3            # publishes the release notes
```

`vMAJOR.MINOR.PATCH` exactly: a tag of any other shape is not a release, is not
what hosts upgrade to, and does not publish notes. Use it for a pre-release
(`v2.0.0-rc1`) when that is what you mean.

The notes come from the Conventional Commits between this tag and the previous
release. Preview them before tagging:

```bash
python3 scripts/release-notes.py v1.2.3 --since v1.2.2
```

Re-pushing a tag rewrites that release's notes rather than duplicating them.
Commits whose subject predates the hook are listed under "Other changes" —
nothing is silently dropped.

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
| shellcheck | `shellcheck -S warning -x scripts/*.sh scripts/lib/*.sh scripts/tests/*.sh deploy/*/entrypoint.sh` | Fix the finding. A `# shellcheck disable=` needs a reason on the same line; the harnesses disable SC2034 file-wide because their values are read inside `check()` eval strings. |
| shell harnesses | `for t in scripts/tests/test-*.sh; do bash "$t"; done` | Install/upgrade scripts are tested with mocked docker; keep it that way. |
| licences | `python scripts/check-licences.py python backend/requirements.lock` (and the sandbox sets, and `node frontend`) | A weak-copyleft or unknown licence must be named in `NOTICE`; strong copyleft is refused outright. Metadata that misstates a licence goes in `scripts/licence-overrides.json` with a reason. |
| dependency audit | `pip-audit`, `npm audit`, Trivy on images | Bump the dependency. Runtime Python versions live in `backend/requirements.lock` (hashed, regenerated with `uv pip compile`, see the file header); direct dependencies in `requirements.txt`. |

## Phone layout audit

`frontend/scripts/phone-audit.mjs` checks the phone layout of every route at
360, 390 and 768 px: no sideways scrolling, no wide table without a scroller,
touch targets of at least 44x44 px and text fields of at least 16 px (iOS
zooms into smaller ones). It is not in CI because it needs a running stack and
a signed-in admin. Run it before you merge anything that touches the phone
layout:

```bash
cd frontend
npx playwright install chromium   # once
PHONE_AUDIT_URL=http://127.0.0.1:5173 PHONE_AUDIT_USER=<admin> PHONE_AUDIT_PASSWORD=<password> \
  npm run audit:phone -- --routes=/app/chat --widths=360
```

Leave out `--routes` and `--widths` to audit everything; `--verbose` lists each
finding. The small-target and small-field counts are compared with
`frontend/scripts/phone-audit.baseline.json`, per route and width. Counts may
only go down: when one drops, lock it in with `--update`; raise one only on
purpose, with `--update`, and say why in the commit. Sideways scrolling and
unwrapped tables are never baselined. They always fail.

## Dependencies

- Python runtime: edit `backend/requirements.txt`, regenerate
  `backend/requirements.lock` (command in its header), commit both. The Docker
  image and CI install only from the lock.
- Python tooling: edit `backend/requirements-dev.in`, regenerate
  `backend/requirements-dev.txt` (command in its header, compiled under the
  runtime lock as a constraint so the two never disagree about a shared
  package), commit both. Every transitive version is pinned and hashed.
- Sandbox / broker images: `sandbox/requirements.in` →
  `sandbox/requirements.txt` (same for `sandbox-broker/`), hashed; the images
  install with `--require-hashes`.
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
