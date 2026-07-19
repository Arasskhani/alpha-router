# Alpha Router Security Operations Runbook

This runbook is intentionally secret-free. Do not paste passwords, API keys,
tokens, connection strings, or plaintext configuration into tickets, logs, or
Git.

## Service health

```powershell
docker compose ps
Invoke-WebRequest http://localhost:8080/health -UseBasicParsing
docker compose logs --tail=100 alpha-router
```

The public health response is deliberately minimal:

```json
{"status":"ok","service":"alpha-router"}
```

It does not prove that every dependency is healthy. Check PostgreSQL,
PgBouncer, Redis, MinIO, and Sandbox Broker separately with
`docker compose ps` and their health status.

## Security signals

Super Admins with the Operations permission can review process-local counters
at:

```text
GET /api/admin/operations/observability
```

Counters include Redis fallback, SSRF blocks, CSRF failures, denied OpenAPI
requests, production-guard warnings, broker failures, repeated 401 responses,
budget-hold leaks, and migration failures. Counters are per worker/process and
reset on restart; they are diagnostic signals, not fleet-wide billing or audit
records.

Investigate repeated events rather than disabling the control. For example:

- `redis_fallback`: verify Redis health and authentication; do not expose the
  Redis password in logs.
- `ssrf_block`: inspect the feature and destination class, never log sensitive
  URL query strings.
- `csrf_failure`: check browser session/CSRF state and origin configuration.
- `docs_denied`: expected for anonymous or non-Super-Admin requests.
- `production_guard_warning`: replace the named configuration category and
  prefer `PRODUCTION_GUARD_MODE=hard-fail` after validation.

## Rollback

Keep the previous image identifier and configuration backup outside Git.
For a local Compose rollback, restore the previous image/configuration and
recreate only the affected service:

```powershell
docker compose up -d --force-recreate alpha-router
docker compose ps
Invoke-WebRequest http://localhost:8080/health -UseBasicParsing
```

Do not remove database, Redis, or MinIO volumes during an application rollback.

## Data-key rotation recovery

1. Stop and preserve the failing application image/log context.
2. Keep the old key available through the approved secret-management process.
3. Restore the database backup in an isolated environment first.
4. Verify decrypt/read behavior without printing plaintext.
5. Re-run migration only after the cause is understood.
6. Rotate the old credential after recovery if it was exposed.

## Sandbox recovery

If the Sandbox Broker is unhealthy, Code Interpreter should fail closed while
normal chat remains available. Check:

```powershell
docker compose ps sandbox-broker
docker compose logs --tail=100 sandbox-broker
```

Do not restore a Docker socket or enable a subprocess fallback in Alpha Router as a
quick fix.
