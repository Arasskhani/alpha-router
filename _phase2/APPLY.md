# Alpharouter — Phase 2 (Security & functional fixes) — applying the changes

Branch: `fix/phase2-security-functional` (22 commits: 15 Phase 2 + 7 from the Phase 0–2 self-review) on top of `fix/phase1-stop-the-bleeding` (`6d499da`).
Head: `2c82124`. 120 files, +4940 / −572.

If you already fetched the earlier head `3bbfd8b`: the same fetch command below fast-forwards the branch (the first 15 commits are unchanged).

Prerequisite: `fix/phase1-stop-the-bleeding` must exist locally at `6d499da`
(applied from `_phase1`). Check with `git rev-parse --short fix/phase1-stop-the-bleeding`.

## Option A — git bundle (recommended)

```powershell
cd C:\APPS\alpha-router
git bundle verify _phase2\alpharouter-phase2.bundle
git fetch _phase2\alpharouter-phase2.bundle fix/phase2-security-functional:fix/phase2-security-functional
git checkout fix/phase2-security-functional
git log --oneline fix/phase1-stop-the-bleeding..HEAD      # 22 commits expected
```

## Option B — patches

```powershell
cd C:\APPS\alpha-router
git checkout -b fix/phase2-security-functional fix/phase1-stop-the-bleeding
git am --3way _phase2\patches\*.patch
```

## Commits

| # | Commit | Step | Scope |
|---|--------|------|-------|
| 1 | 2c09418 | 2.1 | SAML: strict + signed assertions locked (`ALLOW_INSECURE_SAML`), InResponseTo bound to a Redis-tracked AuthnRequest, assertion-id replay cache, fail-closed 503 without Redis |
| 2 | 2f8b270 | 2.2 | Public projects: implicit viewer gets only view/chat.read/resource.read; memory, media, members, invitations, config members-only; going public requires `confirm_public_name` |
| 3 | 31f1b4e | 2.3 | `core/prompt_fences.py`: web/search/document/learned-memory text fenced as untrusted in default chat; Agent path shares it |
| 4 | 474aaa7 | 2.4 | Clear-all-logs / delete-all-media: Super Admin + typed phrase verified server-side + audit before delete; connection/key/personal-key deletions audited |
| 5 | 5e7e7b4 | 2.5 | ClamAV + OOXML bomb checks on chat attachments, voice notes, project media (`core/archive_safety.py`); extraction in a thread under `ATTACHMENT_EXTRACT_TIMEOUT_SECONDS` |
| 6 | b30fd96 | 2.6 | `unlimited_budget` column; key with limit ≤ 0 → 402 unless explicitly unlimited; backfill keeps existing keys working |
| 7 | 07e1e87 | 2.7 | Reconcile locks before summing (Postgres canary proves old code wrote 0 over a live hold); advisory lock 56023116; rollover on locked row |
| 8 | 5568977 | 2.8 | Video runner: `LeaseLost` stops a taken-over runner; poll loop commits before waiting; cancel refuses when provider already completed (409) |
| 9 | 3a20204 | 2.9 | `core/redis_client.get_redis()`: one client per worker/loop; seven call sites; closed in lifespan |
| 10 | 732f4e6 | 2.10 | psutil sampling, audio temp file I/O, base64 encoding off the event loop |
| 11 | 056b5fc | 2.11 | Scheduler `misfire_grace_time=300`, coalesce, server tz; per-user cleanup minute honoured (`*/15` poll); budget reset on UTC trigger without day guard |
| 12 | 63148a6 | 2.12 | No resend of a paid POST after read timeout; `IMAGE_REQUEST_TIMEOUT_SECONDS` everywhere; `OPENROUTER_MAX_CONNECTIONS`, `CHAT_PROVIDER_TIMEOUT_SECONDS`, `VIDEO_MAX_DURATION_SECONDS` enforced |
| 13 | 6432b9f | 2.13 | Hardening batch (17 items): dev-only loopback/private origins, constant-time master key, IP guard fail-closed, XLSX formula escape, NUL/size on streaming update, bootstrap password to 0600 file, no writes in GETs, STT suffix whitelist + WAV sanity, LDAP prune ratio/empty guard, report schedule validation, chat_session ownership, connection base_url SSRF, OIDC endpoints SSRF, default-model gate, active-connection filter, capacity by key owner, `ALLOW_INSECURE_SAML` production flag |
| 14 | 3008910 | 2.14 | nginx: `server_tokens off`, `access_log off`, Mozilla-intermediate ciphers, tickets off, 64m log tmpfs; `app.migrate` retries connection errors; `stack.sh` shows db-init log on failure |
| 15 | 3bbfd8b | 2.15 | Frontend: `lib/sse.ts` (last line, no-space `data:`, cancel on exit), memoised `MarkdownContent`, stable message keys, local calendar days |

### Phase 0–2 self-review (regressions found and fixed, gaps closed)

| # | Commit | Kind | Scope |
|---|--------|------|-------|
| 16 | a1b3c7a | **regression fix** | 2.13 (B-26) made an *unknown* `chat_session_id` a 404 — this broke attachments and voice notes in Private Mode and in brand-new chats whose session is created client-side and synced later. Unknown ids are opaque again (treated as "no server session"); only an *existing* session owned by someone else without `chat.write` project access is refused |
| 17 | 59e680b | gap | `budget_hold_leak` metric existed since Phase 0 but nothing incremented it — now counted at every settlement-failure site (proxy, metered, speech, images) |
| 18 | 58fba5d | corrections | leader-election log on synchronous acquire; SAML rejection audit uses `resolve_client_ip`; connection `base_url` SSRF check off the event loop (`to_thread`); per-user media cleanup slot built in server tz then converted to UTC (was off by the tz offset); CI `scripts-tests` image has bash/openssl; import order |
| 19 | 720d740 | gap (B-37) | `GET /media/{id}` answers HTTP Range with a partial object-storage GET (206 / 416) instead of reading the whole object into memory; multi-range and non-range still read fully |
| 20 | 05f588b | polish (B-36, B-38, B-39, B-40) | voice endpoint reports `media_pending` / `media_error` (quota checked synchronously); ChatPanel shows it; STT sessions joined with a space; docs text; `default_kinds` in model catalog; duplicate `COMPOSE_PROJECT_NAME`; `/tmp` tmpfs 10g → 2g; nginx JSON body ceiling compared as well as the upload ceiling |
| 21 | 904386a | test | await the now-async connection base_url validator |
| 22 | 2c82124 | ops (boot smoke test) | app loggers (`app.*`) run at `APP_LOG_LEVEL` (default INFO) while root stays WARNING — the leader line and other INFO messages were being dropped; `stop_scheduler()` idempotent (every worker exit raised `SchedulerNotRunningError`) |

## Verification performed in the cloud workspace

- `pytest backend/tests` (Python 3.12, SQLite): **1363 passed, 6 skipped** (after the review commits)
- **Real boot smoke test** (Postgres 16 + Redis + S3 stub, `uvicorn --workers 2`): `/ready` 200 with qdrant degraded, "This worker is now the scheduler leader" logged exactly once, SIGTERM shutdown with no tracebacks; end-to-end checks of API-key limit/unlimited/blocked/delete-audit, SSRF `base_url` rejection, typed-phrase log purge, Private-Mode attachment upload
- Postgres 16 canary (`RUN_POSTGRES_RESERVATION_CANARY=1`): `python -m app.migrate` + reservations, reconcile race, scheduler leader, readiness — **11 passed**
- `ruff check backend` — clean
- `scripts/tests/test-backup-flow.sh` 8/8, `scripts/tests/test-deploy-mode-pg-rotation.sh` 5/5; shellcheck warning count unchanged (pre-existing SC2034s)
- Frontend: `tsc` clean, `vitest` 41 files / 224 tests, `vite build` ok, `check-frontend-sources.sh` ok
- Upgrade simulation on Postgres for 2.6: column dropped, legacy rows seeded, `app.migrate` added the column and backfilled (no-cap → unlimited, capped → false)

## Operator notes after deploying

1. New `.env` keys (all have safe defaults): `ALLOW_INSECURE_SAML=false`, `SAML_REQUEST_TTL_SECONDS=600`,
   `ATTACHMENT_EXTRACT_TIMEOUT_SECONDS=30`, `OPENROUTER_MAX_CONNECTIONS=32`, `CHAT_PROVIDER_TIMEOUT_SECONDS=600`,
   `VIDEO_MAX_DURATION_SECONDS=`, `LDAP_PRUNE_MAX_RATIO=0.5`.
2. **SAML needs Redis** now (request tracking + replay cache). Redis is already required by `/ready`.
3. **API keys**: after `app.migrate`, keys that had no positive limit are flagged *Unlimited* in Admin → API Keys. Review them; a key that should be capped gets a limit and the flag off. New keys must have a limit or be explicitly unlimited.
4. **Public projects**: non-members lose access to memory, media, members and the custom prompt (chats + resources stay). Tell project owners.
5. **Uploads**: chat attachments, voice notes and project media are now scanned by ClamAV (fail-closed while `CLAMAV_REQUIRED=true`); with ClamAV down, uploads answer 503 until it is back.
6. **Admin destructive actions** (clear all logs / delete all media) require Super Admin and the typed phrase — UI updated.
7. **Bootstrap admin password** no longer appears in container logs; `install.sh` prints it once from `/app/tls/bootstrap-admin.txt` and removes the file.
8. New `.env` key `APP_LOG_LEVEL=INFO` (app loggers only; root stays WARNING). Set `DEBUG` when diagnosing.
9. Providers on private/internal addresses (Ollama, vLLM on the LAN): the connection `base_url` SSRF check rejects RFC1918/loopback targets unless `ALLOW_SSRF_PRIVATE_RANGES=true` is set — set it **before** editing such connections in Admin.
10. After deploy, `grep "scheduler leader" <backend log>` should show exactly one line per boot — that is the confirmation that the leader election worked and that INFO logging is on.
11. `.env`: with `ENVIRONMENT=production`, `http://localhost:8080` / RFC1918 origins are no longer accepted for CSRF/CORS — `FRONTEND_URL` must be the real origin.
12. Push: `git push -u origin fix/phase2-security-functional` (the cloud session has no push access to the GitLab origin).

## Deferred / not in this phase

- The image strategy fallback loop still retries a *different strategy* after a read timeout (documented product decision about Gemini drops); only the transport-level resend of the same POST was removed.
- Review item #8 (mid-stream kill on budget exhaustion) remains a product decision.
- Phase 3 (ruff full rule set, mypy baseline, eslint/knip, conftest, requirements.lock, dead code) is next per the plan.
