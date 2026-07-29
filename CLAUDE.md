# Alpha Router — Codebase Map & Working Notes

Reference document produced from a full line-by-line read of the repository
(≈85,000 LOC excluding `node_modules` / `.venv` / lockfiles).
Purpose: let anyone (human or agent) orient in this codebase without re-reading it.

Last full read: 2026-07-29.

---

## 1. What Alpha Router is

An **organizational AI control plane**. It sits between employees and upstream LLM
providers (OpenRouter, OpenAI, Anthropic, Google, xAI, …) and enforces budgets,
RBAC, quotas, audit logging and retention.

Three surfaces, one FastAPI process:

| Surface | Path | Auth |
|---|---|---|
| User app (chat, media, activity, recommendations) | `/app/*` | HttpOnly session cookie + CSRF |
| Admin panel | `/admin/*` | same cookie, RBAC menu gating |
| OpenAI-compatible gateway | `/v1/*` | Alpha Router API key (`Authorization: Bearer alpha_router_…`) |

The React SPA is compiled into `frontend/dist` and served by the same FastAPI app
(`main.py:568-596`, SPA fallback with path-traversal containment).

---

## 2. Repository layout

```
Alpha Router/
├── backend/
│   ├── app/
│   │   ├── main.py              app factory, lifespan, production guard, SPA serving
│   │   ├── config.py            pydantic-settings Settings + INSECURE_DEFAULTS
│   │   ├── database.py          async engine (+ optional read replica), get_db/get_read_db
│   │   ├── db_migrate.py        1201 lines — schema patcher + 21 flagged one-time migrations
│   │   ├── sandbox_broker.py    STANDALONE FastAPI app (runs in its own container)
│   │   ├── api/                 19 routers (~7k LOC)
│   │   ├── models/              13 ORM modules
│   │   ├── services/            78 modules (~20k LOC) — all real logic lives here
│   │   ├── core/                security.py (JWT/bcrypt/api-keys), language_detect.py
│   │   └── utils/               app_attribution.py, display.py
│   ├── tests/                   82 files, 11.6k lines, plain pytest + asyncio.run
│   └── requirements.txt
├── frontend/                    React 18 + Vite 5 + TS 5.6 SPA (~30k LOC src)
├── sandbox/                     code-interpreter container image (runner.py)
├── sandbox-broker/              Dockerfile only; app code is backend/app/sandbox_broker.py
├── deploy/seaweedfs/            entrypoint.sh + pinned VERSION (4.40)
├── scripts/                     PowerShell ops scripts (Windows host)
├── docs/                        security audit + operations runbook
├── docker-compose.yml           postgres, pgbouncer, redis, seaweedfs, sandbox-broker, alpha-router
├── Dockerfile                   multi-stage: node build → python 3.12-slim + playwright chromium
└── .gitlab-ci.yml               backend tests, frontend test+build, pip-audit, npm audit, trivy
```

### Runtime topology (Compose)

```
browser ──► alpha_router:8080 (uvicorn, 4 workers, read_only rootfs, cap_drop ALL)
              ├─► pgbouncer:6432 (transaction pooling) ──► postgres:16
              ├─► redis:7 (rate limits, OIDC/2FA/SSO state, litellm cache)
              ├─► seaweedfs:8333 (S3 API, all media blobs)
              └─► sandbox-broker:8081  [network: sandbox_control, internal]
                        └─► docker.sock ──► spawns alpha-router-sandbox:latest per execution
```

`sandbox_control` is an internal Docker network; the broker port is never published.
The **Docker socket mount on the broker is the residual host trust boundary**
(audit finding F-01).

---

## 3. Configuration

Single source: `backend/app/config.py` → `Settings` (env-prefixed, `.env` file).
`.env.example` (199 lines) is the documented template; `.env` is git-ignored.

Key knobs by group:

- **Environment gate** — `ENVIRONMENT` (`development` | `production`),
  `PRODUCTION_GUARD_MODE` (`hard-fail` | `warning`).
- **DB** — `DATABASE_URL` (via PgBouncer), optional `DATABASE_READ_URL`,
  `DB_POOL_SIZE=12` / `DB_MAX_OVERFLOW=20` / `DB_POOL_TIMEOUT=45`, `UVICORN_WORKERS=4`.
  Sizing target documented in `.env.example`: 5,000 concurrent users, ~25k sessions.
  `statement_cache_size=0` is mandatory (PgBouncer transaction mode + asyncpg).
- **Auth** — `SECRET_KEY`, `JWT_EXPIRE_MINUTES=480`, `ENABLE_COOKIE_AUTH=true`,
  `ALLOW_LEGACY_BEARER_AUTH=false`, `ENABLE_CSRF=true`, cookie/header names.
- **Crypto** — `DATA_ENCRYPTION_KEY` (falls back to `SECRET_KEY`-derived legacy key).
- **Gateway** — `GATEWAY_MASTER_KEY`.
- **Sandbox** — `SANDBOX_BROKER_TOKEN` (≥32 chars), `CODE_SANDBOX_BROKER_URL`,
  `CODE_SANDBOX_TIMEOUT_SECONDS=20`, `ALLOW_INSECURE_CODE_SUBPROCESS=false`.
- **Bounded I/O** — 11 `MAX_*` byte/pixel/count ceilings, all runtime-clamped.
- **Budget holds** — `BUDGET_*_FALLBACK_HOLD_USD`, `BUDGET_MAX_HOLD_USD=5`,
  `BUDGET_RESERVATION_TTL_SECONDS=7200`.
- **SSRF** — `ALLOW_SSRF_PRIVATE_RANGES=false`, `ENABLE_SSRF_DNS_PINNING=true`.
- **Headers** — `CONTENT_SECURITY_POLICY` (empty = not enforced),
  `CONTENT_SECURITY_POLICY_REPORT_ONLY` (default set in code), `ENABLE_HSTS`.
- **Storage** — `S3_*`, `MEDIA_CDN_PREFIX=cdn`, `SEAWEEDFS_ADMIN_PASSWORD`.
- **Identity providers** — `LDAP_*`, `SAML_*`, `OIDC_*` (env is only a fallback;
  DB rows in `auth_providers` written from Admin → Authentication take precedence).

### Production startup guard

`main.py:164-357`. No-op unless `ENVIRONMENT=production`. Collects insecure defaults
across 20+ categories (placeholder secrets, missing broker token, unauthenticated
Redis, empty data key, public OpenAPI, cleartext SAML/OIDC/SMTP/S3/frontend/API URLs,
HSTS off on a public surface, insecure code subprocess, legacy Bearer auth) and either
raises `RuntimeError` (`hard-fail`) or logs (`warning`). Loopback and single-label
Compose hostnames are deliberately accepted so single-box installs still boot.

---

## 4. Data model (`backend/app/models/`)

| Table | Notes |
|---|---|
| `users` | RBAC `role` slug + `user_role_assignments` (many), `auth_provider`, `token_version` (JWT revocation counter), directory fields (`department`, `office`, `job_title`, `reporting_to`), budget cache (`monthly_budget_usd`, `budget_used_usd`, `budget_reserved_usd`, `budget_period_start`), TOTP (`totp_secret_encrypted`, `totp_backup_codes_hashed`), `deleted_at` (soft delete) |
| `user_groups`, `user_group_members` | source = `local` \| `ldap` \| `saml` |
| `user_role_assignments` | (user_id, role_slug) PK |
| `connections`, `connection_audit_logs` | provider credentials, `api_key_encrypted` (Fernet), model-sync schedule |
| `ai_models` | catalog synced from providers; pricing normalized to per-1k; Alpha Router never edits pricing |
| `alpha_router_api_keys`, `alpha_router_api_key_audit_logs` | gateway keys with credit limit + reset period + expiry |
| `user_api_keys` | per-user keys; debit the user's monthly budget |
| `budget_plans`, `plan_assignments` | plan assignable to user / group / department |
| `budget_reservations` | in-flight holds; `idempotency_key` unique, `status` held/settled/released/expired |
| `request_logs` | one row per billed request; unique index on `budget_reservation_id` |
| `chat_sessions`, `chat_messages`, `chat_folders`, `chat_message_feedback`, `user_chat_prefs` | normalized chat store; `revision` for optimistic concurrency; unique `(session_id, sequence)` and `(session_id, client_message_id)` |
| `media_assets` | S3 object key + `content_hash` (deduped per user), `expires_at` |
| `user_media_preferences` | per-user cleanup schedule |
| `user_connectors` | per-user OAuth client + tokens, all Fernet-encrypted |
| `auth_providers` | ldap / saml / oidc config JSON (sensitive fields encrypted) |
| `smtp_settings`, `report_schedules`, `system_settings`, `system_metric_snapshots` | |

Schema is created with `Base.metadata.create_all` under a PG advisory lock, then
`apply_schema_column_patches()` adds any missing ORM columns/indexes (always
nullable, no defaults — see §9 drift note). There is **no Alembic version history**
despite alembic being installed; migrations are the flag-driven functions in
`db_migrate.py`.

---

## 5. Auth & RBAC

### Session flow

1. `POST /api/auth/login` → local bcrypt, falls through to LDAP.
2. If TOTP enabled → `requires_2fa` + `pending_token` (Redis, 300 s) →
   `POST /api/auth/login/2fa`.
3. SSO (SAML ACS / OIDC callback) issues a **one-time exchange code** (Redis, 30 s)
   consumed by `POST /api/auth/sso/exchange`.
4. `session_cookie.set_session_cookies` writes:
   - `alpha_router_session` — HttpOnly, `path=/api`, SameSite=Lax
   - `alpha_router_csrf` — readable, `path=/`, double-submit token

`Secure` is only set in production, with an explicit carve-out for same-origin HTTP
on RFC1918 addresses (single-box LAN installs).

### Dependencies (`api/deps.py`)

- `get_current_user` — cookie first; Bearer only if `allow_legacy_bearer_auth`.
  Rejects: no token, bad token, unknown user, `deleted_at` set,
  `jwt["ver"] < user.token_version`. **Deliberately does not check `is_active`** —
  disabled users retain read-only access to their own history.
- `require_active_user` — adds the `is_active` check.
- `require_rbac_menu(menu, write=)` → 21 generated `require_<menu>` /
  `require_<menu>_write` pairs.
- `require_super_admin` — used only by data-key rotation and admin 2FA disable.
- `get_bearer_token` — returns the raw JWT unvalidated, for the headless-PDF
  renderer to re-authenticate as the caller.

### RBAC semantics (`services/rbac.py`, 554 lines)

Permissions are **role slugs**, not scoped strings. 21 menu definitions in 7
categories. Only three assignable roles remain in the catalog:
`user`, `super_admin`, `api_keys_full_administrator` — every other menu is
Super-Admin-only. Legacy slugs are expanded by `expand_legacy_role_slug` (the
`rbac_removed_roles_v1..v4` migrations exist to collapse the old catalog).
`user_can_write_menu` is **least-privilege**: write requires *every* role granting
menu access to also permit writes. `USER_APP_MENUS = {chat, media, recommendations,
user_manual}` are always writable.

### CSRF

`services/csrf_protection.py` — pure-ASGI middleware, no body read. Enforced on
unsafe methods under `/api/` **only when a session cookie is present**. Origin
allowlist = `frontend_url` + `127.0.0.1:8080` + `localhost:8080` + any
`http://<RFC1918>`. `EXEMPT_PATHS` (login, 2FA, SSO/SAML exchange) keep the Origin
check; `/api/auth/saml/acs` is fully exempt.

The `/v1` gateway is outside `/api/` and therefore outside CSRF entirely — it is
API-key auth only and never touches RBAC.

---

## 6. The LLM request path

`services/proxy_service.py` (902 lines) is the heart of the system.

```
POST /api/chat/completions  (api/chat.py)
  └─ preflight_stream_chat(db, …)          # on the REQUEST session, still open
       ├─ resolve_model_and_key()          # AIModel + decrypted key + base_url
       └─ reserve(...)                     # budget hold, 402 if over limit
     [route commits]
  └─ stream_chat(ResolvedStreamContext)    # opens its OWN AsyncSessionLocal
       ├─ augment_messages_with_tools()    # web search / web fetch / code-interpreter
       ├─ apply_prompt_cache_breakpoints() # cache_control: ephemeral
       ├─ list_tools_for_user()            # MCP connectors → function schemas
       ├─ acompletion(stream=True)  ──► async for chunk:
       │     ├─ re-emit as `data: {...}\n\n`
       │     ├─ ChatCompletionPersister.on_content (flush every 0.45 s / 64 chars)
       │     ├─ request.is_disconnected() / is_cancel_requested() → stop emitting,
       │     │   keep consuming upstream so usage is still captured
       │     └─ accumulate tool_calls by index
       ├─ MCP loop         (MAX_MCP_ITERATIONS = 3)
       ├─ Code loop        (MAX_CODE_ITERATIONS = 3)
       └─ finally: _compute_cost() → log_usage() in an INDEPENDENT session
                   → settle(reservation, actual_usd, request_log_id)
                   → `data: [DONE]`
```

Notes that matter when editing this path:

- The billing session is intentionally decoupled from the persistence session so a
  persister rollback can never drop the `RequestLog` (`proxy_service.py:743-748`).
- Elapsed time is measured to the **last chunk** (`stream_end_at`), not wall clock.
- `_should_retry_non_stream` works around a LiteLLM "without having called read()"
  bug by retrying the whole request non-streamed.
- `_compute_token_cost_usd` prefers catalog per-1k rates, then
  `litellm.completion_cost`, then 0. Negative provider prices are normalized to NULL
  at sync time and by the `pricing_sanity` migration.
- `configure_litellm_cache()` (called from lifespan) wires a Redis cache when
  `REDIS_URL` is set, else in-memory; `caching: True` on every call.

### Image generation

`api/images.py` (1306 lines) + `services/openrouter_image_service.py` +
`services/image_model_resolver.py`. Auto-Router scores candidates on
stability 400 / latency 200 / satisfaction 250 / capabilities 150 / newness 50, with
a hard 0.70 success-rate floor (≥8 samples → ×0.35 demotion). Retries with
1/2/4/6 s backoff; failover on `is_image_model_failover_error`. Billing goes through
`image_billing_service.log_image_usage` → the same `log_usage`.

### Budget reservations

`services/budget_reservation_service.py` (380 lines): **reserve → settle → release**.

- Estimate: chat ≈ `utf8_bytes/3` prompt tokens + clamped `max_tokens` output, ×1.25,
  floored at `BUDGET_CHAT_FALLBACK_HOLD_USD`, ×4 when the code interpreter is on.
- Reserve: `SELECT … FOR UPDATE` on `users` / `alpha_router_api_keys`, idempotency key
  `{subject_type}:{subject_id}:{key}`, 402 when `used + held + amount > limit`.
- Settle: subtract the full hold from the reserved counter, add the actual to used.
- Sweepers: `expire_stale_reservations` (5-min job, `FOR UPDATE SKIP LOCKED`),
  `reconcile_subject_reserved`, `release_open_holds_for_subject` (month/period rollover).
- Fallback when settle didn't apply: atomic `UPDATE users SET budget_used_usd = … + :cost`.

---

## 7. Backend service clusters

`services/` has 78 modules. Grouped:

- **Auth/identity** — `auth_config`, `auth_urls`, `auth_exchange`, `twofa_pending`,
  `oidc_client` (PKCE, signed state cookie, JWKS cache, RS256/ES256 only),
  `saml_sp` (python3-saml), `ldap_config` / `ldap_auth` / `ldap_winldap` (Windows
  signed LDAP via pythonnet) / `ldap_sync`, `auth_sync_scheduler`, `username_norm`,
  `user_service`, `user_role_service`, `rbac`, `user_lifecycle_service`,
  `user_account_cleanup_service`, `totp_service`, `password_policy`.
- **Billing** — `budget_service`, `budget_reservation_service`,
  `image_billing_service`, `plan_assignment_service`, `alpha_router_api_key_service`,
  `alpha_router_api_key_audit`, `connection_audit`, `transfer_limits_service`.
- **Chat** — `proxy_service`, `chat_completion_persistence`,
  `user_chat_storage_service` (1097 lines; revisions, 512 KB message cap, PG FTS
  search with SQLite LIKE fallback), `chat_title_service`, `voice_refine_service`,
  `image_prompt_service`, `chat_tools_service`, `code_interpreter_service`,
  `chat_feedback_service`, `chat_import_export` (alpha-router / ChatGPT / Open WebUI
  formats), `chat_export_service` (Playwright PDF), `chat_docx_service`,
  `transcription_service`, `attachment_policy`, `attachment_extract`.
- **Media/storage** — `storage_service`, `object_storage_service` (boto3),
  `user_media_service`, `media_authorization_service` (404-not-403 existence hiding),
  `image_decode_policy` (fail-closed Pillow), `storage_migration_service`.
- **Catalog** — `model_sync`, `model_capabilities`, `llm_providers`,
  `prompt_cache_service`.
- **Connectors/MCP** — `connector_registry` (frozen 11-provider allowlist,
  exact-URL SSRF gate), `connector_state`, `mcp_client_service` (JSON-RPC over HTTP
  with SSE fallback).
- **Security/observability** — `secret_crypto` (Fernet, PBKDF2 480k),
  `csrf_protection`, `security_headers`, `ssrf_guard` (DNS-pinned transport),
  `rate_limit` (Redis sorted-set sliding window), `session_cookie`, `docs_guard`,
  `bounded_io`, `observability` (9-event in-process counters), `db_monitor_service`.
- **Reporting** — `reports_catalog` (30 reports), `reports_service` (1363 lines,
  pandas/openpyxl/reportlab), `activity_service`, `activity_pdf_service`
  (headless-Chromium screenshot PDF), `log_export_service`, `operations_service`,
  `operations_time_range`, `recommendations_service`.
- **Scheduling/lifecycle** — `scheduler` (APScheduler: model sync 30 min, budget
  reset monthly, reservation expiry 5 min, storage cleanup 03:00, chat retention
  04:00, chat stats 03:30, user media hourly, metrics snapshot hourly),
  `schedule_timezone`, `retention_policy_service`, `migration_flags`, `smtp_service`.

---

## 8. Frontend

React 18 + Vite 5 + TypeScript 5.6, no state library — `useState` + refs + 3
contexts + module singletons in `lib/`.

- Scripts: only `build` (`tsc -b && vite build`) and `test` (`vitest run`).
  **No `dev` script** — use `npx vite`. Dev proxy: `/api` → `localhost:8080`.
- Routing (`App.tsx`): `/login`, `/admin/*` behind `PrivateAdmin` →
  `AdminLayout` → `ReadOnlyProvider` → `AdminPermissionGuard` → `Shell`;
  `/app/*` behind `Private` → `UserLayout` → `ReadOnlyRouteGuard`.
  30 admin routes, 6 user routes.
- `api.ts` (155 lines) is the only network layer: `authFetch` adds `X-CSRF-Token`
  from the `alpha_router_csrf` cookie on unsafe methods, always `credentials: "include"`,
  and hard-redirects to `/login` on 401. No typed endpoint layer — pages call
  `api<T>("/api/…")` inline.
- **`ChatPanel.tsx` is 4559 lines, one component**: ~50 `useState`, ~30 refs,
  manual SSE reading (`res.body.getReader()` + `TextDecoder`, `data:` lines,
  `[DONE]`), delta coalescing into a single `requestAnimationFrame` flush,
  per-session `AbortController` map, a per-session prompt queue with serialized
  drain, image generation run **outside React** in `lib/chatImage.ts`, attachments
  encoded as `__ALPHA_ROUTER_ATTACH_JSON__:` and images as `__ALPHA_ROUTER_IMAGE_JSON__:`.
- **Private mode** is per-session and irreversible: nothing is persisted server-side,
  media goes to IndexedDB (`alpha_router_private_media`), attachments are processed in the
  browser, and everything is wiped on logout unless `alpha_router_private_persist === "1"`.
- Cross-tab: `BroadcastChannel("alpha-router-chat-sync")` + Web Locks leader election
  (`lib/chatLeader.ts`).
- `lib/chatStorage.ts` (1918 lines) is the client-side sync engine: dirty sets,
  pending-append queue, revision conflicts (409) with retry/reconcile, incremental
  `since` sync, message cache in sessionStorage.
- `styles.css` is 8358 lines / ~1290 rules, single flat file, BEM-ish naming.
  Tokens in `:root`, dark mode via `[data-theme="dark"]` overrides. RTL/Persian is
  handled per-element from JS (`lib/textDirection.ts`) — `dir` is never set globally.
  PDF/DOCX export is server-side specifically for Persian/RTL fidelity.

---

## 9. Known defects & risks

Collected during the read. Nothing here has been changed.

### Correctness — high impact

| # | Location | Problem |
|---|---|---|
| 1 | `services/scheduler.py:52-56` | `job_storage_cleanup` never commits → the nightly media retention purge is a **silent no-op**. Every sibling job commits. |
| 2 | `services/scheduler.py:68-71` | `job_user_media_cleanup` runs at `minute=0` then skips when `now.minute < prefs.cleanup_minute` → any user with `cleanup_minute > 0` is **never cleaned up**. |
| 3 | `services/model_sync.py:142-152` | `sync_connection_with_flash` selects `AIModel` with **no connection filter** — disables the whole catalog, syncs one connection, re-enables everything. Resurrects deliberately disabled models across all connections. |
| 4 | `services/log_export_service.py:27` vs `:70` | Column declared `"Latency ms"`, emitted as `"Duration ms"` → exported latency column is all-NaN. |
| 5 | `api/chat.py:64-68`, `api/admin.py:285-289` | `GET` handlers execute `DELETE FROM ai_models` + commit when there are no connections. Destructive mutation on a GET, and the chat one is reachable by an **inactive** user. |
| 6 | `services/chat_title_service.py:136`, `voice_refine_service.py:165`, `image_prompt_service.py:251` | All three make real `acompletion` calls and never call `log_usage` → **unmetered, unbilled spend**. |
| 7 | `services/user_chat_storage_service.py:810,845` | `_next_sequence` = read `MAX(sequence)` then increment in Python → duplicate `sequence` under concurrency (the unique constraint turns it into a 500). |
| 8 | `services/alpha_router_api_key_service.py:60-63` | `apply_expiration` sets `is_active = False` then `ensure_key_usable` raises → the route rollback discards it, so expired keys are never persistently disabled. |
| 9 | `services/ldap_sync.py:170-172` | Prune compares a normalized (lower-cased) stored username against un-normalized LDAP values → mixed-case AD accounts without `external_id` get **soft-deleted**. |
| 10 | `api/logs.py:95,97` | Unguarded `strptime` on `start_date`/`end_date` → 500 instead of 400. `end_date` also drops the last 59 seconds of the day. |
| 11 | `services/reports_service.py:620-650` | `report_slow_models_latency` ignores its `latency_ms` threshold entirely. |
| 12 | `services/rate_limit.py:59,65-71` | Sorted-set scores come from `time.monotonic()`, whose epoch is **per process**. The "shared across workers" window trims the wrong entries. `count > limit` (Redis) vs `len >= limit` (memory fallback) also differ by one. |
| 13 | `services/mcp_client_service.py:96` | `_refresh_if_needed` commits the session it is handed — from `stream_chat` that is the live streaming session. |
| 14 | `services/db_monitor_service.py:118,129` | `psutil.cpu_percent(interval=…)` blocks ~0.25 s and is called from async code without `to_thread` → stalls the event loop on every Operations load. |

### Permission / security gaps

| # | Location | Problem |
|---|---|---|
| 15 | `api/reports.py:241-259` | `POST /schedules/user` only needs `require_active_user`, does **not** validate `report_type` against the catalog, and accepts arbitrary `recipients` + `parameters_json`. Any active user can queue a service-wide report to any email address. |
| 16 | `api/reports.py:207-220` | `list_schedules` returns every row including other users' schedules → leaks recipient addresses. |
| 17 | `api/reports.py:184,192` | `/preview` and `/export` are reads gated on `require_reports_write` — **inverted permission**; a read-only reports role can do nothing. |
| 18 | `api/smtp.py:60-73` | `test_smtp` connects to an arbitrary caller-supplied host:port with no allowlist (SSRF / port-scan primitive) and returns the raw exception string with HTTP 200. |
| 19 | `api/smtp.py:44-57` vs `:39` | `save_smtp` never persists `use_ssl`, but `get_smtp` returns it → the SSL toggle silently does nothing. |
| 20 | `services/saml_sp.py:113-118`, `model_sync.py:50,99` | Admin-supplied URLs fetched with plain `httpx.Client(follow_redirects=True)`, bypassing `ssrf_guard`. |
| 21 | `api/user_connectors.py:247,348` | OAuth token exchange / revoke use bare `httpx.AsyncClient` instead of `ssrf_guard.safe_client` (bounded by the registry allowlist, but inconsistent). |
| 22 | `services/totp_service.py:75-88` | Backup codes are 8 hex chars (32 bits) hashed with a **single unsalted SHA-256** — offline-brute-forceable from a DB dump. No TOTP replay cache. |
| 23 | `services/secret_crypto.py:161-162` | `decrypt_secret` returns the input unchanged when both keys fail → a mis-rotated key silently ships ciphertext upstream as an API key. |
| 24 | `services/csrf_protection.py:50-53` | `http://127.0.0.1:8080` / `http://localhost:8080` are always allowed origins, including in production. |
| 25 | `services/activity_pdf_service.py:215-227` | Injects the caller's session JWT into headless Chromium pointed at `frontend_url`; a misconfigured `frontend_url` leaks the token, and the self-request can deadlock a single-worker deployment. |
| 26 | `services/code_interpreter_service.py:73-91` | The AST blocklist covers `import`/`__import__` only — `open`, `eval`, `exec`, `getattr` chains are not blocked. Real isolation is the broker container. |
| 27 | `sandbox_broker.py:389` | `--tmpfs /tmp:rw,exec,…` permits execution from `/tmp` inside the sandbox. |
| 28 | `services/security_headers.py:12-18` | No default enforced CSP — only Report-Only. `BaseHTTPMiddleware` is used here and in `docs_guard`, which is known to interfere with streaming backpressure (relevant given SSE chat). |
| 29 | `services/ldap_config.py:58` | `discover_root_dse` always uses `Tls(validate=ssl.CERT_NONE)`. |
| 30 | `config.py:99` + `api/gateway.py:87,136` | `gateway_master_key` defaults to `sk-alpha-router-master` and is compared with `==` (non-constant-time), granting a full service identity with no RBAC. |

### Scaling

- `operations_service.py:565-569` and `activity_service.py:394-408` load **every**
  `RequestLog` in the window into Python and aggregate there — O(buckets × sources × N).
- `user_media_service.py:111-138,272-277` loads all matching `MediaAsset` rows and
  paginates in Python.
- `storage_migration_service.py:308-334` holds every media blob in memory before
  writing.
- N+1 patterns: `user_role_service.py:90-107`, `plan_assignment_service.py:93-115`,
  `reports_service.py:229,918,928,971`.

### Data / migration hygiene

- `db_migrate.py:61-63` — patched columns are always added **nullable with no
  default**, so upgraded databases drift from ORM `nullable=False`.
- `db_migrate.py:525-841` — the four `rbac_removed_roles_v1..v4` migrations are
  byte-identical logic; all four rewrite `user_role_assignments` on every fresh boot.
- ~15 bare `except Exception: pass` blocks around DDL and `SELECT`s coerce real DB
  errors into "table absent" (`db_migrate.py:886,980,993,1073,1088,1103`).
- `retention_policy_service.py:229` and `user_account_cleanup_service.py:63-67`
  delete `ChatMessage` without touching `ChatMessageFeedback` — correctness depends
  entirely on a DB cascade.
- `services/ldap_config.py:152` uses a backslash inside an f-string expression →
  **Python ≥3.12 is a hard requirement**.

### Frontend defects

- `MyActivity.tsx:10`, `Recommendations.tsx:34`, `UserProfile.tsx:133` compare
  `user.role === "admin"` but `normalizeRole` maps `admin → full_administrator` →
  admins see the wrong back-link and the label "User".
- `ChatPanel.tsx:3883,3904,3930` render `<li>` inside `<li>` (invalid DOM).
- `chatStorage.ts:903-913,1421-1432` mutate objects held in React state in place
  with no `setState` → rendered data silently diverges.
- `chatStorage.ts:81` and `:516-522`, `user_chat_storage_service.py:138` — dead
  branches where both sides are identical (`language` pref is unreachable).
- Three concurrent pollers fight over the same session: 1.2 s message poll, 5 s
  pending-image poll, and the 400 ms-debounced refresh — each with its own merge.
  `chatLeader.broadcastChatRefresh` also fires locally, so every save re-enters the
  refresh path.
- `ChatPanel.tsx:2808,3201,3252` read `streamingSessions` state instead of the ref →
  a delete/retry in the same tick as a send can slip through.
- ~8 unhandled promise rejections (`void x.then(...)` with no `catch`) in
  `ChatPanel`, `Authentication.tsx`, `Groups.tsx`, `Connections.tsx`, `Users.tsx`.
- `@tanstack/react-virtual` is a dependency but imported nowhere;
  `ChatSidebarVirtual.tsx` is an unvirtualized `<ul>`.
- ~35 dead exports in `lib/` (all of `privateModeMigration.ts`, 12 `@deprecated`
  symbols in `chatStorage.ts`). `ToolCallCard.tsx` is imported nowhere.
- `styles.css:6553,6574` use `var(--card)`, which is **never defined**.
- Accessibility: `Modal.tsx` has no focus trap or focus restore; `MessageInfoButton`
  is a focusable button with no `onClick`; messages keyed by array index;
  drag-and-drop is mouse-only; many `<label>` without `htmlFor`.
- Positive note: **zero `any` / `as any`** in `src/`, and no TODO/FIXME markers
  anywhere in the repo.

### Dead code worth deleting

- `deps.py` — `require_admin`, `require_admin_write`, the `require_rbac_category`
  factory and all 14 category aliases have zero call sites, plus ~12 unused menu pairs.
- **Scheduled reports are write-only**: `ReportSchedule` rows are created and listed
  but no service ever reads them. No scheduler job, no PATCH/DELETE, no toggle.
- Duplication hot spots: the activity-payload assembly block is copy-pasted 5×
  (`admin.py` ×4, `groups.py`, `user_routes.py`); the `prompts_period` normalization
  7×; `admin.py:2492-2639` duplicates `user_media.py:33-152` almost field-for-field;
  `connection_audit.py` ≡ `alpha_router_api_key_audit.py`; `humanSize` re-implemented in 4
  frontend files; four separate parsers for the `__ALPHA_ROUTER_IMAGE_JSON__` format.
- `groups.py` and `user_routes.py` import **private** helpers from `app.api.admin`,
  making `admin.py` a de-facto shared library rather than just a router.

---

## 10. Tests & CI

- 82 files, 11,596 lines in `backend/tests/`. **No `conftest.py`, no `pytest.ini`,
  no `pytest-asyncio`.** Convention: `async def _test_x()` + `def test_x():
  asyncio.run(_test_x())`.
- Each test builds its own `sqlite+aiosqlite:///:memory:` engine. Two files need
  `StaticPool` to share one in-memory DB (`test_secret_crypto.py`,
  `test_data_key_rotation.py`).
- Exactly one file targets real PostgreSQL:
  `test_budget_reservations_postgres.py`, skipped unless
  `RUN_POSTGRES_RESERVATION_CANARY=1`.
- Frontend: **4 vitest files**, all pure functions, no config file (so
  `environment: "node"`, no jsdom). Zero component or integration tests.
- CI (`.gitlab-ci.yml`): `verify` stage = backend pytest + frontend `npm test` &
  build; `audit` stage = `pip-audit`, `npm audit --audit-level=high`, and
  `trivy image --exit-code 1 --severity CRITICAL,HIGH` against the pinned
  SeaweedFS image.
- Coverage gaps: gateway `/v1` end-to-end, the MCP/code-interpreter agentic loops in
  `stream_chat`, `reports_service` report bodies, `activity_pdf_service`, the
  scheduler jobs (which is how defects #1 and #2 survived), and the whole frontend.

---

## 11. Security posture (per `docs/ALPHA_ROUTER_SECURITY_AUDIT_FRESH_REPORT.md`)

Findings on record: **F-01 Critical** — Docker socket on `sandbox-broker`.
**High** — F-02 production guard soft-fail, F-03 legacy Bearer bypasses CSRF,
F-04 app bound to all interfaces on `:8080`. **Medium** — F-05 rate-limit
fail-open, F-06 CSP Report-Only only, F-07 SSRF kill-switches exist, F-08 legacy
plaintext decrypt fallback, F-09 private-mode client-side confidentiality, F-10
broker without explicit non-root `USER`. **Low** — F-11 master key compared with
`==`, F-12 masked secrets reveal last 4 chars, F-13 `dangerouslySetInnerHTML` in
`ChatCodeBlock`. **Informational** — F-14 users-menu admins can read any media
(by design).

`docs/SECURITY_OPERATIONS_RUNBOOK.md` is the operational counterpart: health
checks, the `/api/admin/operations/observability` counter list, the production
configuration gate checklist, rollback procedure, data-key-rotation recovery, and
sandbox recovery.

**Current `.env` state:** all application secrets (SECRET_KEY 64,
DATA_ENCRYPTION_KEY 64, POSTGRES/REDIS/S3/SEAWEED/SANDBOX tokens 32–64 chars) are
real, non-placeholder values. `ENVIRONMENT` is set, `PRODUCTION_GUARD_MODE=hard-fail`.
Two issues: the file contains ~20 stray keys that look pasted from container images
(`GOSU_VERSION`, `PG_SHA256`, `PYTHON_VERSION`, `MC_CONFIG_DIR`, `PGDATA`, …), and
`POSTGRES_USER` / `POSTGRES_DB` are empty while `docker-compose.yml` expects them
(Compose defaults them to `alpha-router`, so it works, but it is fragile).

---

## 12. Working conventions in this codebase

- **All logic in `services/`.** Routers validate, call one or two services, and
  shape the response. Follow that.
- **Commit explicitly.** Several handlers rely on `get_db`'s exit-time commit
  (`admin.py:1536,1560,2574`, `user_media.py:87`). Don't add more; commit in the
  handler.
- **Never write DDL by hand for a new column.** Add it to the ORM model;
  `apply_schema_column_patches` picks it up. For data changes, add a flagged
  migration in `db_migrate.py` + a key in `migration_flags.py`.
- **All outbound user-influenced HTTP goes through `ssrf_guard.safe_client` +
  `bounded_io.bounded_get_bytes`.** There are existing violations (§9 #20, #21);
  don't add more.
- **All secrets at rest go through `secret_crypto.encrypt_secret`** (idempotent).
- **Cost must flow through `log_usage`.** Any new `acompletion` call needs a
  reservation and a `log_usage`, or it is unbilled (§9 #6).
- **Pricing is read-only from providers.** Never write to `ai_models.*_cost_per_1k`
  outside `model_sync`.
- Python **3.12+** required. Frontend has no `dev` script — `npx vite`.
- Tests: no pytest-asyncio; follow the `asyncio.run` wrapper convention and build a
  local in-memory engine.
