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
PgBouncer, Redis, SeaweedFS, and Sandbox Broker separately with
`docker compose ps` and their health status.

Object storage (SeaweedFS):

```powershell
docker compose ps seaweedfs
# S3 API (localhost only): http://127.0.0.1:8333
# Admin UI (localhost only): http://127.0.0.1:23646
.\scripts\security-check-object-storage.ps1
```

## Security signals

Super Admins with the Operations permission can review process-local counters
at:

```text
GET /api/admin/operations/observability
```

Counters include Redis fallback, SSRF blocks, CSRF failures, denied OpenAPI
requests, production-guard warnings, broker failures, repeated 401 responses,
and budget-hold leaks. Counters are per worker/process and
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
  keep `PRODUCTION_GUARD_MODE=hard-fail` in production. The default is now
  fail-closed; use `warning` only for a deliberate, temporary migration.

## Production configuration gate

Set `ENVIRONMENT=production` only with a deployment-specific secret/config
source. The startup guard refuses insecure fallbacks without logging values.
Before starting, verify the following categories are explicitly configured:

- unique application, admin, service-admin, gateway, Redis, broker, database,
  data-encryption, and object-storage credentials;
- authenticated Redis and admin-only OpenAPI documentation;
- HTTPS for the public API, frontend, and SAML ACS/metadata URLs when SAML is enabled;
- TLS for SMTP and object storage, plus `ENABLE_HSTS=true`;
- `ALLOW_INSECURE_CODE_SUBPROCESS=false` and a reachable authenticated broker.

Do not place real values in `.env.example`, tickets, CI logs, or this runbook.
After a clean boot and validation, rotate credentials through the approved
secret-management process. Credential rotation is intentionally separate from
this code/configuration tranche.

## Rollback

Keep the previous image identifier and configuration backup outside Git.
For a local Compose rollback, restore the previous image/configuration and
recreate only the affected service:

```powershell
docker compose up -d --force-recreate alpha-router
docker compose ps
Invoke-WebRequest http://localhost:8080/health -UseBasicParsing
```

Do not remove database, Redis, or SeaweedFS volumes during an application rollback.

### Object storage (SeaweedFS)

Alpha Router uses SeaweedFS only (`seaweedfs` Compose service) and the intended
Stage 8 bucket name `alpha-router-media`.

```powershell
# Security surface check (host)
.\scripts\security-check-object-storage.ps1

# Inventory / backup current SeaweedFS bucket
.\scripts\backup-object-storage-baseline.ps1 -EndpointUrl http://127.0.0.1:8333
```

Pin SeaweedFS image updates via `deploy/seaweedfs/VERSION` and
`docker-compose.yml` / CI `SEAWEEDFS_IMAGE` together.

## Data-encryption-key recovery

Alpha Router has one fail-closed encryption key and no historical-key reader.
If `DATA_ENCRYPTION_KEY` is lost or changed, stop the application and restore
the correct value through the approved secret-management process. Never print
stored ciphertext or plaintext while diagnosing the mismatch. A deliberate key
change requires a fresh deployment and data reset.

## Sandbox recovery

If the Sandbox Broker is unhealthy, Code Interpreter should fail closed while
normal chat remains available. Check:

```powershell
docker compose ps sandbox-broker
docker compose logs --tail=100 sandbox-broker
```

Do not restore a Docker socket or enable a subprocess fallback in Alpha Router as a
quick fix.
