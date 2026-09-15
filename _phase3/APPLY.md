# Alpharouter — Phase 3 (Engineering hygiene) — applying the changes

Branch: `chore/phase3-engineering-hygiene` (11 commits) on top of `fix/phase2-security-functional` (`2c82124`).
Head: `8292e88`. 473 files, +22605 / −19375 (≈ 17k of that is the one-time `ruff format` pass and the hashed lock file).

Prerequisite: `fix/phase2-security-functional` must exist locally at `2c82124` (the 22-commit version from the
re-delivered `_phase2` zip). Check with `git rev-parse --short fix/phase2-security-functional`.

## Option A — git bundle (recommended)

```powershell
cd C:\APPS\alpha-router
git bundle verify _phase3\alpharouter-phase3.bundle
git fetch _phase3\alpharouter-phase3.bundle chore/phase3-engineering-hygiene:chore/phase3-engineering-hygiene
git checkout chore/phase3-engineering-hygiene
git log --oneline fix/phase2-security-functional..HEAD      # 11 commits expected
```

## Option B — patches

```powershell
cd C:\APPS\alpha-router
git checkout -b chore/phase3-engineering-hygiene fix/phase2-security-functional
git am --3way _phase3\patches\*.patch
```

## Commits

| # | Commit | Step | Scope |
|---|--------|------|-------|
| 1 | 4f1aef9 | 3.1 | `ruff format` over backend/ — mechanical, AST-preserving, kept separate so the next diff is only real changes |
| 2 | 1723e92 | 3.1 | ruff full rule set (E,F,W,B,UP,SIM,C90,BLE) + `ruff format --check` as CI gate. Real fixes: 81 `assert False` → `pytest.fail`, E402 in admin.py, a `return` inside `finally` in the video runner that would have swallowed an in-flight exception, `raise … from exc`, `zip(strict=)`, nested ifs, `contextlib.suppress`. 22 functions > complexity 20 carry `# noqa: C901 -- Phase 4 split`; 144 blind excepts carry `# noqa: BLE001 -- <reason>` derived from what the handler does (31 are silent `pass` handlers and say so) |
| 3 | ba6ff5a | 3.1 | mypy in CI against `backend/mypy-baseline.txt` (`scripts/mypy-check.sh`, mypy-baseline). 144 errors/42 files frozen; new errors fail. Two real fixes: an f-string backslash mypy cannot parse, and `import app.models` shadowing the package name `app` in main.py (45 bogus errors) |
| 4 | 4eecc9e | 3.1 | Frontend ESLint 9 flat config (typescript-eslint, react-hooks, jsx-a11y). 0 errors; 286 pre-existing warnings are a budget (`--max-warnings 286`) that may only be lowered. Fixed: 12 unused symbols, 4 comboboxes without `role`/`aria-controls`, `prefer-const`, control-regex disables with reasons |
| 5 | 4043db6 | 3.2 | pytest-asyncio (`asyncio_mode=auto`); libcst codemod turned 320 `asyncio.run(run())` tests into `async def` and 336 other `asyncio.run` into `await`; `tests/conftest.py` (`engine`, `session_factory`, `db_session`, `user`, `admin`, `client`); **OpenAI contract test** for `/v1/chat/completions`; stream error frames now `{"error": {"message","type","code"}}` (was a bare string); `requirements-dev.txt`; pytest runs from `backend/` |
| 6 | 95acb36 | 3.3 | `backend/requirements.lock` (hashed, Linux/3.12, 124 packages, constrained to the versions the whole Phase 0–3 suite ran on); Dockerfile `wheels` stage — runtime image has no compiler/-dev packages; `sandbox/` and `sandbox-broker/` fully pinned `requirements.txt`; CI installs from the lock; `renovate.json` (digest pinning, weekly, no automerge for SAML/crypto/LDAP) |
| 7 | dee5e5d | 3.4 | `estimate_*_hold` + `_clamp_hold` and the six `BUDGET_*_FALLBACK_HOLD_USD` settings removed (no production caller since pricing snapshots) |
| 8 | 80cc4bc | 3.4 | 20 unreferenced backend symbols removed (rbac helpers, `export_activity_dashboard_pdf`, async wrappers, `ping_clamav`, …); `vulture --min-confidence 80` in CI with `vulture_whitelist.py`. Agent platform untouched |
| 9 | f9cbdf4 | 3.4 | Frontend: 112 unused exports / 25 types / `@tanstack/react-virtual` gone; 37 dead functions deleted; `UserPrefs.language` and the write-only `msgcache` removed; `npm run knip` in CI |
| 10 | 361e214 | 3.5 | `app/core/constants.py` (`normalize_openrouter_base_url`, `OPENROUTER_*`, `RRF_K`); ACL CHECK constraint shared; outbound HTTP timeouts → 4 settings; `global_default_chat_model` + `global_default_transcription_model` folded into `system_default_models` |
| 11 | 8292e88 | 3.6 | `.pre-commit-config.yaml` (system hooks = CI tools), Conventional Commits commit-msg hook (`scripts/check-commit-message.py` + test), `CONTRIBUTING.md` |

## Verification performed in the cloud workspace

- `pytest` (SQLite): **1371 passed, 6 skipped** — all tests now native async.
- Postgres 16 canary: `python -m app.migrate` + 4 canary files: **11 passed**.
- `ruff check` + `ruff format --check`: clean. `vulture ≥80%`: clean. `scripts/mypy-check.sh`: 0 new.
- Frontend: eslint 0 errors (286 warnings = budget), `tsc -b` clean, knip clean, vitest **224 passed**, `vite build` ok.
- Shell harnesses 3/3 (incl. new commit-message test). `pre-commit run --all-files`: all hooks pass.
- Lock: `pip wheel --require-hashes` → offline `pip install` → `pip check` → `import app.main` in a fresh venv: ok (the exact sequence the new Dockerfile runs).
- Real 2-worker boot on Postgres + Redis + S3 stub: `/ready` 200, `/v1/models` 200 with the master key, "scheduler leader" logged once, SIGTERM clean.

## Operator notes after deploying

1. **Docker image must be rebuilt** (`Dockerfile` restructured, installs from `requirements.lock`). First build downloads the same package versions as before; the runtime layer shrinks (no build-essential).
2. **CI needs Node 20 + Python 3.12 as before**; new jobs: `backend-typecheck`; `backend-lint` now also runs `ruff format --check` and vulture; frontend job runs `npm run lint` and `npm run knip`. Expect the first pipeline to take a few minutes longer.
3. New `.env` keys (defaults = the old literals): `PROVIDER_HTTP_TIMEOUT_SECONDS=60`, `PROVIDER_LOOKUP_TIMEOUT_SECONDS=20`, `IDENTITY_HTTP_TIMEOUT_SECONDS=20` (OIDC client was 15 before), `SPEECH_HTTP_TIMEOUT_SECONDS=120`. Removed keys: `BUDGET_{CHAT,EMBEDDING,IMAGE,VIDEO,AUDIO,TOOL}_FALLBACK_HOLD_USD` — delete them from `.env` (they were ignored anyway).
4. **Gateway clients**: a provider failure mid-stream is now `data: {"error":{"message":"…","type":"provider_error","code":null}}` (OpenAI shape) instead of `{"error":"…"}`. The Alpharouter UI accepted both already; check any custom client that parsed `error` as a string.
5. **OpenRouter base URL**: connections saved as `https://openrouter.ai` (no `/api/`) are now normalised to `https://openrouter.ai/api/v1` in *all* code paths (model sync and video included, which previously would have hit the HTML site).
6. Developers: `pip install pre-commit && pre-commit install --install-hooks -t pre-commit -t commit-msg` (see `CONTRIBUTING.md`). Commit subjects must be Conventional Commits, ≤ 100 chars — note that eight Phase 1–3 subjects in history exceed 100 chars; the hook applies going forward.
7. Renovate: the build host had no registry access, so base-image `@sha256` digests are not pinned in this branch; Renovate's first run (config `:pinDigests`) adds them. Until then, tags are version-pinned as before.
8. Windows developers keep using `requirements.txt` (the lock is Linux/3.12 for the image and CI; `pythonnet` is win32-only and therefore not in it).
9. Push: `git push -u origin chore/phase3-engineering-hygiene` (the cloud session has no push access).

## Deviations from the plan (deliberate)

- `line-length` stays 120 (already configured) instead of 110 — changing it would only add churn.
- `UP042` (str+Enum → StrEnum) is ignored with a reason: it changes `str()`/`format()` of enum members and belongs in a behaviour-reviewed commit, not a lint pass.
- BLE001 reasons are derived per handler action, not hand-written per site; the 31 silent `pass` handlers are explicitly labelled as the Phase 4 backlog.
- The 103 per-test `create_async_engine` helpers were **not** mass-migrated to the new fixtures: they work, and a codemod would have to understand each file's seeding. New tests use `conftest.py`; the migrated `test_system_default_chat_model.py` shows the pattern.
- Kept (tests-only but complete features, product decision): `maybe_save_generated_media_to_project`, `compute_image_cost_usd`, `frontend/scripts/export-combined-docs.tsx`.
- ESLint stays on 9.x: `eslint-plugin-jsx-a11y` does not declare ESLint 10 support yet.
- commitlint is replaced by a dependency-free Python check with the same rules.

## Deferred / not in this phase

- Phase 4 items surfaced by the gates: 22 functions above complexity 20 (`# noqa: C901`), 31 silent `except: pass`, 130 React-Compiler-rule warnings (setState-in-effect, refs) and 91 unlabeled form controls — all visible in-tree and budgeted, none may grow.
- mypy baseline has 144 errors (87 `arg-type`); shrinking it is ongoing work, one MR at a time with `scripts/mypy-check.sh --sync`.
