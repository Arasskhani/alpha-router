# Alpharouter — Phase 4 "Architecture" — apply instructions

Branch: `refactor/phase4-architecture` (23 commits = 12 Phase 4 + 7 from the
self-review + 4 for API Logs detail) on top of
`chore/phase3-engineering-hygiene` (`2556f1e`). 98 files, +7386 / −2367.

**This replaces the earlier `_phase4` deliveries.** If you already fetched the
branch, fetch again — the bundle fast-forwards it.

## Apply

```powershell
cd C:\APPS\alpha-router
git fetch _phase4\alpharouter-phase4.bundle refactor/phase4-architecture:refactor/phase4-architecture
git checkout refactor/phase4-architecture
git push -u origin refactor/phase4-architecture
```

Alternative (no bundle): `git checkout -b refactor/phase4-architecture chore/phase3-engineering-hygiene && git am _phase4\patches\*.patch`.

## Commits

| # | Commit | Step | Change |
|---|--------|------|--------|
| 1 | 7dcddfc | 4.3 | Alembic owns the whole schema: legacy baseline revision `0000a1b2c3d4` (40 tables, idempotent), catch-up revision `4b0c1d2e3f4a`, ORM aligned with the DB, drift gate test (`tests/test_schema_baseline.py`), **no DDL in uvicorn workers** — `python -m app.migrate` runs alembic upgrade → legacy catch-up (flag) → validate |
| 2 | aeafa60 | 4.2 | 15 money columns Float → `NUMERIC(20,12)` / prices `NUMERIC(24,14)` (revision `5c1d2e3f4a5b`, Postgres only); `alpharouter_budget_reserved_drift_usd` gauge + `budget_reserved_drift_repaired` event |
| 3 | 57a758e | 4.1 | `provider_utils.py`, `usage_logging_service.py`, `model_resolution_service.py` extracted from proxy_service (re-exports kept) |
| 4 | 1379a29 | 4.1 | `turn_settlement.py` — `settle_turn(TurnIdentity, TurnOutcome)` replaces stream_chat's finally block |
| 5 | cbef1d7 | 4.1 | `chat_turn_context.py` — `build_turn_context()`, `CapacityLease`, `NonGeneratingReply` |
| 6 | 9e50937 | 4.1 | `provider_stream.py` (`ProviderAttempt`, `NonStreamRetry`, `estimate_tokens`), `code_interpreter_turn.py` |
| 7 | 9d5ce0b | 4.5 | Agent platform is a preview behind `AGENTS_PLATFORM_ENABLED=false`: routers not mounted, agent chat fields → 400, menu hidden via `/api/auth/session.features` |
| 8 | 44c8c0b | 4.6 | `React.lazy` for all 44 pages + `Suspense` + `RouteErrorBoundary` (root + per-route). Initial chunk 1.79 MB → 380 kB |
| 9 | 27a53d4 | 4.6 | chatStorage: sync-by-diff keyed on `clientMessageId`; full-history pagination; prompt-deletion PUT reconciles against the full server list (was: pushed the loaded 50-row window → **wiped older history on long chats**); `mergeRemoteChatSessions` honours `updatedAt` |
| 10 | 2dca717 | 4.6 | 18 pure helpers from ChatPanel → `lib/chatPanelMessages.ts` + tests (ChatPanel 7517 → 7319 lines) |
| 11 | f558fe0 | 4.7 | compose `logging: json-file 50m×5` for all 13 services; `install.sh` clones the newest `vX.Y.Z` tag instead of `main` |
| 12 | 9213b78 | 4.7 | Request-body ceiling published through Redis (`alpharouter:request_body_limit_mb`), state file kept as fallback |
| 13 | a513c68 | review | **Two regressions in #9.** (a) A local row whose `clientMessageId` is missing looked new, so an image/speech placeholder replaced in place by an error notice was **appended a second time** instead of patched; id-less rows now pair with the next unmatched server row of the same role. (b) The diff is restricted to a contiguous tail — appending a middle row moves it to the end and scrambles the order — which also makes a partial server window safe, so the history walk stops once it covers the local list (**one request per ordinary turn again**, not one per 200 messages). (c) Taking every field from the newer copy could revert a model switch or tool toggle that had not been pushed yet; a session with queued writes keeps its local fields |
| 14 | 895dcd0 | review | **Upgrade hazard in #7.** A chat remembers its Agent locally, so with the preview off (the new default) every message in a chat that had an Agent selected returned **400 "The Agent platform is not enabled"** — and the picker is disabled once the catalog 404s, so the user could not clear it. The selection is ignored while the feature is off, the picker is hidden, the catalog is not fetched. Backend test pins that `agent_auto_route: false` (sent on every ordinary turn) is *not* an Agent request |
| 15 | 49925b2 | review | **Resource leak in #5.** Only the two augmentation blocks released the Code Interpreter permit and the budget hold on failure; a raise anywhere else in preparation (provider kwargs, Auto Router probe, workspace inventory, persister) held a concurrency slot until TTL and left the hold stuck. Whole preparation guarded; `abandon()` made idempotent so a slot is never released twice |
| 16 | 9f7d6a2 | review | **Retry bug in #1.** Only the success path disposed the engine, so a step that failed part-way left a pool bound to a closed loop and every retry died on "attached to a different loop" — a transient database hiccup became a failed `db-init` |
| 17 | 7123f53 | review | **Cache bug in #12.** The Redis cache sentinel `0.0` reads as "checked just now" while `monotonic()` is small, so a worker could serve its first seconds without ever asking Redis |
| 18 | bd05840 | review | **Upgrade hazard in #11.** Cloning a tag leaves a detached HEAD; `upgrade.sh` read that as the branch "HEAD" and ran `git pull origin HEAD`, quietly fast-forwarding a pinned host **onto main**. A pinned checkout now moves release to release, or warns and stops. New harness `scripts/tests/test-release-pin.sh` |
| 19 | 6ac8a59 | review | **Follow-up to #13.** The identity guard skipped the patch when one side had no id — exactly the replaced-in-place rows — so speech/video error notices never reached the server. It now refuses only when both ids exist and differ |
| 20 | 0b7277a | logs | **A recorded failure is never blank again.** `str(exc)` is empty for every httpx timeout, a bare ConnectError and `asyncio.TimeoutError`, and every failure path stored exactly that — which is why a failed video reached the user as "Video generation failed" and the container log read `Video job <id> failed:` with nothing after it. `describe_failure()` gives a stable code, a message that always says something (class name, HTTP status, method + host with the query stripped, a slice of the error body) and the upstream status. Wired into the video worker, the chat error formatter (a timeout used to send a blank SSE error frame), transcription, chat titles, image prompts. Two video holes closed: `RuntimeError(None)` (literally "None") when a provider ends a job with no reason, and the adapter dropping a structured `error` object |
| 21 | b768284 | logs | Revision `6d2e3f4a5b6c`: `request_logs.error_code`, `http_status`, `correlation_id`, `provider_job_id` (three indexed). `log_usage` — the single writer of that table — takes them and defaults the correlation id to the current request's. The video worker runs inside `correlation_scope(job_id)`, so its log lines and its row share one id, and a failed video records the OpenRouter job id |
| 22 | addc57f | logs | API Logs shows it: a **Type** column (chat / video / image / speech / embedding, read from the usage operation), a status cell that names the failure with the full text on hover, and two new filters (request type, failure reason) offered from the values actually present. The detail modal opens with a **Failure** block — reason, HTTP status, provider job id, correlation id to grep the server log with — and each attempt shows its connection, quantity and timing. **Export follows the page**: Type, Error Code, HTTP Status, Error, Correlation Id, Provider Job Id in the list CSV; per-attempt connection, window, quantity and error in the single-request CSV |
| 23 | 72d604a | logs | The provider's own response per attempt (`usage_events.raw_usage_json`) and the video job's last poll payload were stored but never shown and never cleared. The modal now shows them behind a disclosure and the single-request CSV carries them (8000 chars/attempt). Their lifetime is yours: **"Keep provider payloads N days"** in the API Logs toolbar (1–365, same button style as Filter/Export, behind the admin write lock). Saving applies immediately and writes a security-audit entry; a daily job at 04:10 does the routine sweep. Purging nulls the payload and keeps the row, so costs, tokens, status and the failure reason stay as long as the request log |

## Operator notes — read before deploying

1. **Rebuild the image and run migrations explicitly.** Workers no longer create tables or add columns at boot. `scripts/upgrade.sh` already runs `db-init` (`python -m app.migrate`) before the app; if you start uvicorn by hand, run `python -m app.migrate` first. On a DB that predates Alembic the baseline revision stamps itself over the existing tables (every `CREATE` is guarded).
2. **New env keys** (both in `.env.example`):
   - `LEGACY_SCHEMA_BOOTSTRAP=true` — keeps the legacy `create_all` + column-patch catch-up inside `app.migrate` for one more release. Set `false` once `tests/test_schema_baseline.py` passes against a copy of production (0 drift), then the chain alone owns the schema.
   - `AGENTS_PLATFORM_ENABLED=false` — Agent Studio / Knowledge / Evaluations / Governance routers and `/api/agents` are not mounted; the chat Agent picker is hidden and chats that had an Agent selected fall back to a plain turn. Set `true` to keep today's behaviour.
3. **Money migration `5c1d2e3f4a5b`** rewrites 15 columns with `ALTER … TYPE NUMERIC USING ROUND(col::numeric, s)`. It takes an `ACCESS EXCLUSIVE` lock per table for the rewrite — on `request_logs` this is the big one; expect seconds to a few minutes depending on row count. Run during a maintenance window; take the pre-upgrade backup (`upgrade.sh` does).
4. **Numeric values are still Python floats in the ORM** (`asdecimal=False`) — no call-site change; the storage is exact.
5. **Redis body-limit key**: after the first Storage transfer-limit save (or HTTPS activate) the key exists; before that, workers read the state file as today. The middleware does one Redis `GET` per worker per 5 s (250 ms timeout, 30 s back-off when Redis is down).
6. **Frontend chat sync**: an ordinary turn is one request; a chat longer than the loaded window pages through as much history as the local list needs. Prompt deletion reads the whole history and refuses (with a message) above 5000 messages rather than truncating it.
7. **`install.sh`** on a fresh host installs the newest release tag and leaves a detached HEAD; `upgrade.sh` then moves that host release to release. `ALPHAROUTER_GIT_REF=main` restores the old behaviour. Until the first `vX.Y.Z` tag exists on the remote it falls back to `main` with a warning — **tag a release** before pointing new hosts at it.
8. **API Logs retention**: provider payloads default to **30 days**. The control is in the API Logs toolbar (hidden on the API-key-scoped view). Shortening it purges immediately — that is deliberate, and audited. Everything else in the log is untouched by it.
9. **Patch targets moved** for tests that mock chat internals: `turn_settlement.log_usage/finalize_agent_run/release_code_interpreter_turn/AsyncSessionLocal`, `chat_turn_context.*` (augment_*, persister_from_body, mark_agent_run_started, …). `proxy_service.acompletion` / `run_python_sandbox` still work (injected callables).

## What is NOT in this phase (deliberately)

- **4.1 targets not fully met**: `stream_chat` 1194 → 521 lines (CC ≈150 → ≈75), `proxy_service.py` 2777 → 1370 lines. Plan wanted <300 lines / CC <25. Next step would be a `TurnRunner` class owning the loop state (`_absorb`, `_compute_cost`, `_persist_content`, …) — left for Phase 5 to keep this diff reviewable.
- **4.4 MemoryScope unification** and **4.8 unified `audit_events`** — not started (each ≈1 week, schema-wide). Recommend own branches after the Numeric migration has landed in production.
- **4.6 ChatPanel split** into `ChatSidebar/Composer/MediaGeneration/StreamController/AgentPanel/ExportMenu` — only the pure helpers moved. The sidebar JSX alone reads 65 component-scoped identifiers; a real split must first move sidebar/pagination state into hooks. `styles.css` split not done.
- **4.7 scheduler → `knowledge_scheduler` process** — not moved. Phase 1.5's advisory-lock leader election already guarantees one scheduler per deployment, and admin settings changes call `refresh_*_schedule()` in-process; moving the scheduler out needs a Redis pub/sub for those refreshes first. TLS state (`desired-state.json`, `nginx.conf`, certs) stays on the shared volume because the edge nginx container reads files, not Redis.
- Sandbox containers are created by the broker through the Docker API, so the compose logging limits do not apply to them; they are removed after each run.

## Verification performed (re-run after the review commits)

- Backend: `pytest tests` → **1411 passed, 8 skipped** (SQLite, `REDIS_URL` unreachable); Postgres canary (reservations, reconcile race, scheduler leader, readiness, schema baseline, money numeric) → 13 passed; ruff (full set) + `ruff format --check` clean; mypy baseline: 0 new errors; vulture ≥80 clean.
- Schema: fresh database with `LEGACY_SCHEMA_BOOTSTRAP` **on** and **off** both end at 0 `compare_metadata` diffs against the ORM; money columns verified `numeric(20,12)` / `numeric(24,14)` in `information_schema`.
- Boot smoke: `python -m app.migrate` then `uvicorn app.main:app --workers 2` on Postgres+Redis+moto S3: `/health` 200, `/ready` 200, exactly one "scheduler leader" line, no DDL from workers, no tracebacks, both workers shut down cleanly on SIGTERM.
- Frontend: `tsc -b` clean, ESLint 0 errors / 286 warnings (= budget), knip clean, vitest **258 passed** (45 files), `vite build` initial chunk 380 kB / gzip 119 kB.
- Migration `6d2e3f4a5b6c` applied to a Postgres copy, columns and indexes verified, and the schema drift gate still reports 0 diffs against the ORM.
- Shell: all four `scripts/tests/test-*.sh` harnesses pass, including the new release-pin one; shellcheck clean on the changed files.
- Compose: `docker compose config` with the CI placeholder env renders `logging` for all 13 services (one key per service); the registry overlay still validates.
