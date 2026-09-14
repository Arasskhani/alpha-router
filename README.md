# Alpharouter™

**One route. Every model.**

Alpharouter™ is an organizational AI control plane with a built-in web UI. It
sits between your people (and optional external tools) and upstream LLM
providers such as OpenRouter, OpenAI, Anthropic, Google, and xAI. One platform
enforces budgets, RBAC, quotas, retention, and audit logging while serving
chat, media, activity, and an OpenAI-compatible gateway.

The platform provides three surfaces in a single FastAPI process:

- **User app** (`/app`) — chat, specialist Agents, media library, and personal
  activity
- **Admin panel** (`/admin`) — identity, access, budgets, providers, models,
  reports, operations, storage, Agents, Knowledge, and evaluations
- **OpenAI-compatible gateway** (`/v1`) — Bearer-key access for IDEs, scripts,
  and automation

Alpharouter is OS-independent. Develop on any host with Docker available, and
run the same Compose stack on Linux or any other Docker-capable environment.

## Features

- **Chat** — streaming conversations, attachments, prompt queue, private mode,
  and import/export (Alpharouter, ChatGPT, and Open WebUI JSON)
- **Specialist Agents** — five seeded domain Agents (IT, HR, Legal, Finance,
  Marketing) with Knowledge Bases, ACL, maker-checker approvals, and evaluation
  publish gates
- **Chat tools** — web search, web fetch (SSRF-guarded), image generation,
  video generation, speech, and Code Interpreter
- **Code Interpreter** — networkless disposable containers, measured
  per-model compatibility, Redis admission leases, and cancel-on-Stop
- **Media** — uploads and generated files (images, video, sandbox artifacts)
  with ACL, quotas, and HTTP Range for video
- **Identity** — local accounts with optional TOTP, plus LDAP/Active Directory,
  SAML 2.0, and OIDC
- **Spend control** — plans, monthly user budgets with reservation/settle,
  admin-issued gateway key credits, and personal API keys that debit the
  user’s plan
- **Governance** — RBAC menus, model Public/Private ACL, retention, API logs,
  Activity exports, and Prometheus metrics
- **Knowledge** — document review, ClamAV malware scan, parser sandbox, Qdrant
  indexing, and citation-backed retrieval

## Quick start with Docker

### New Ubuntu Server (`install.sh`)

Use this only on an empty host. It installs git, curl, Docker Engine, and
Compose, clones GitHub if needed, writes `.env` and
`docker-compose.override.yml` (docker.sock GID for Code Interpreter), and
starts the stack.

```bash
curl -fsSL https://raw.githubusercontent.com/Arasskhani/alpha-router/main/scripts/install.sh | sudo bash
```

Or from a checkout (still installs missing host packages):

```bash
sudo ./scripts/install.sh --prod
```

Development mode:

```bash
sudo ./scripts/install.sh --dev
```

Default clone path is `/opt/alpha-router`. Override with
`ALPHAROUTER_HOME=/home/alpha/alpha-router`.

After CI publishes images:

```bash
# In .env: ALPHAROUTER_REGISTRY=registry.gitlab.com/your-group/alpha-router
sudo ./scripts/install.sh --from-registry --image-tag latest
```

`install.sh` has a hard lock: it exits immediately if `.env`,
`docker-compose.override.yml`, `.alpharouter-installed`, named data volumes,
or `alpha-router-*` containers already exist. There is no confirmation prompt
and no override. Use `upgrade.sh` on a live host.

### Existing server with data (`upgrade.sh`)

Use this on a live host that already has `.env` and user data. It never
removes volumes and never runs `docker compose down -v`.

```bash
cd /path/to/alpha-router
./scripts/upgrade.sh --prod
```

Skip image rebuild (keeps current images, refreshes override and starts):

```bash
./scripts/upgrade.sh --prod --skip-build
```

`upgrade.sh` fast-forwards git when the tree is a clone, merges new
`.env.example` keys without overwriting secrets, rewrites
`docker-compose.override.yml`, then `docker compose up`.

Production guard check only:

```bash
./scripts/preflight-prod.sh
```

### Backup, restore and rollback

`upgrade.sh` takes a snapshot before it rebuilds or migrates anything
(`scripts/backup.sh --consistent`, written to `./backups/<timestamp>/`, last
7 kept) and tags the images that were running as `<image>:prev`. Snapshots
hold a `pg_dump` of the database, the Qdrant / SeaweedFS / TLS volumes, `.env`
and a `MANIFEST` with the git commit and image ids.

```bash
./scripts/backup.sh                       # on-demand, online (no downtime)
./scripts/backup.sh --consistent          # stops qdrant/seaweedfs during the copy
BACKUP_DIR=/mnt/backups ./scripts/backup.sh

./scripts/restore.sh 20260914103000                    # database + volumes
./scripts/restore.sh 20260914103000 --previous-images  # roll back a bad upgrade
./scripts/restore.sh 20260914103000 --with-env         # also restore .env
```

Restore stops the stack (volumes are kept), replaces the database contents and
data volumes with the snapshot, and starts the stack again; everything written
after the snapshot is lost. Keep `./backups` (or `BACKUP_DIR`) on separate
storage — it contains `.env` with all secrets. Set `SKIP_BACKUP=1` to upgrade
without a snapshot.

### Manual quick start

```bash
cd alpha-router
cp .env.example .env
docker compose up --build -d
```

Compose builds the code-interpreter image through a one-shot
`alpha-router-sandbox` initializer. Seeing that initializer as `Exited (0)` is
expected; `alpha-router-sandbox-broker` is the long-running service and creates
networkless disposable containers for each execution. No manual sandbox start
is required.

### Local endpoints

| Service | URL |
|---|---|
| UI and API | http://localhost:8080 |
| Health | http://localhost:8080/health |
| PostgreSQL | localhost:5432 (`alpha_router` / `alpha_router`) |
| PgBouncer | localhost:6432 |
| Redis | localhost:6379 |
| Qdrant | http://localhost:6333 |
| SeaweedFS S3 API | http://localhost:8333 |
| SeaweedFS admin UI | http://localhost:23646 |

Bootstrap administrator credentials come from `ADMIN_USERNAME` and
`ADMIN_PASSWORD` in `.env`. Replace every example secret before production use,
including `SECRET_KEY`, `DATA_ENCRYPTION_KEY`, `GATEWAY_MASTER_KEY`,
`SANDBOX_BROKER_TOKEN`, `QDRANT_API_KEY`, database and Redis passwords, and
S3/SeaweedFS credentials.

### Stop the stack

```bash
docker compose down
```

Data volumes are kept by default. To remove them as well:

```bash
docker compose down -v
```

### Follow app logs

```bash
docker compose logs -f alpha-router
```

## Project structure

```text
alpha-router/
├── backend/          FastAPI application, gateway, schedulers, and services
├── frontend/         React and Vite single-page application
├── sandbox/          Isolated code-interpreter image
├── sandbox-broker/   Internal Docker sandbox controller
├── deploy/           SeaweedFS support, registry compose overlay
├── scripts/          install.sh (new host), upgrade.sh (existing data)
├── docker-compose.yml
├── Dockerfile
├── LICENSE
└── .env.example
```

## Deployment

Two supported paths:

| Path | When to use | Command |
|------|-------------|---------|
| **New Ubuntu host** | Empty server, no Docker yet | `sudo ./scripts/install.sh --prod` |
| **Existing host with data** | Live `.env` + volumes | `./scripts/upgrade.sh --prod` |
| **Registry pull (new)** | After GitLab CI `publish-images` | `sudo ./scripts/install.sh --from-registry --image-tag TAG` |
| **Registry pull (existing)** | Same, keep data | `./scripts/upgrade.sh --from-registry --image-tag TAG` |

**Source bundle** (minimum files to copy):

`docker-compose.yml`, `Dockerfile`, `.env.example`, `backend/`, `frontend/`
(including `package-lock.json`), `sandbox/`, `sandbox-broker/`, `deploy/`,
`scripts/`.

**Registry bundle** (lighter; no app source required):

`docker-compose.yml`, `deploy/docker-compose.registry.yml`,
`deploy/seaweedfs/`, `.env.example`, `scripts/`.

Set `ALPHAROUTER_REGISTRY` in `.env` to your registry path (for GitLab,
`$CI_REGISTRY_IMAGE`). Optional `REGISTRY_USER` / `REGISTRY_PASSWORD` for
`docker login` during install.

`--prod` generates strong secrets and runs the production guard preflight.
For public HTTPS deployments, either place your own reverse proxy in front of
`:8080` and set `FRONTEND_URL`, `API_PUBLIC_URL`, and `ENABLE_HSTS`, or upload a
certificate in **Admin → Security → Security Settings** to enable the bundled
TLS edge on port 443 (or another port). After HTTPS is confirmed, set
`ALPHAROUTER_HTTP_BIND=127.0.0.1` so clients cannot skip the edge.

The bundled edge (`alpha-router-edge`) runs on the host network and reaches the
app through its published port, so Docker rewrites the source address to the
bridge gateway. `TRUST_LOCAL_GATEWAY_PROXY=true` (the default) trusts exactly
that one address, which is what lets `X-Forwarded-For` from the edge be honoured
while traffic routed in from outside keeps its real source address. Add
`TRUSTED_PROXY_CIDRS` entries only for an external reverse proxy, and confirm the
detected address in **Admin → Security → Security Settings → Admin IP
Restrictions** before switching the allowlist to enforce.

Machine-specific files (never commit): `.env`, `docker-compose.override.yml`.

## Configuration

Copy `.env.example` to `.env`. Important groups include:

- **Database and cache** — `DATABASE_URL`, optional `DATABASE_READ_URL`, pool
  limits, worker count, rate limits, and `REDIS_URL`
- **Authentication** — local accounts plus optional LDAP, SAML, OIDC, and TOTP
- **Storage** — SeaweedFS through its S3-compatible API using `S3_*` settings
- **Gateway** — `GATEWAY_MASTER_KEY`, administrator-issued `alpha_router_...`
  keys, and user-created personal API keys
- **Public URLs** — `API_PUBLIC_URL` and `FRONTEND_URL`
- **Security** — `TRUSTED_PROXY_CIDRS`, `TRUST_LOCAL_GATEWAY_PROXY`,
  `ALPHAROUTER_HTTP_BIND`, in-product HTTPS (Admin → Security Settings), and
  optional admin IP allowlist
- **Sandbox** — broker URL, token, timeout, and resource limits
- **Agents & Knowledge** — Qdrant, ClamAV, worker, retrieval, evaluation,
  and observability

For production, set `ENVIRONMENT=production` and keep
`PRODUCTION_GUARD_MODE=hard-fail`.

### Agents & Knowledge

Create Agents in **Admin → Agents & Knowledge → Agent Studio**. There is no
built-in system Agent seed: every Agent, Knowledge Base, binding, and evaluation
dataset is operator-owned. Publish immutable versions after maker-checker review,
bind only approved Knowledge releases, and gate production with evaluation when
your policy requires it.

Operational endpoints:

- `GET /health` and `GET /ready` — process and dependency health
- `GET /metrics` — bounded Prometheus metrics (Bearer-protected in production)
- `/admin/agents`, `/admin/knowledge`, `/admin/agent-evaluations` — governance
  and quality control surfaces

Use private mode for non-persistent conversations. Private mode disables
sensitive Knowledge retrieval and memory according to Agent policy; it is not a
way to bypass ACL, budget, audit, or provider-egress controls.

### Code Interpreter

Compatibility with the Code Interpreter tool is measured per connection and
model instead of being hardcoded per vendor, so new models need no code change.
A scheduled job probes due models in small claimed batches (Python block →
sandbox execution → artifact → follow-up turn), and real chat turns feed the
same registry. Repeated hard failures such as `MALFORMED_FUNCTION_CALL`
quarantine a model; transient provider errors do not. Verified and blocked
models also shape OpenRouter Auto Router constraints per request.
Administrators can review evidence, probe on demand, or pin a decision from
Admin → Models → Code Interpreter.

Turns use a Redis-backed lease shared by all API workers. The default admission
ceiling is 200 end-to-end turns, with a separate per-user/API-key ceiling.
Requests above capacity are rejected before provider or budget reservation work
with HTTP `429` and `Retry-After`; Redis outages fail closed for this feature.
Operators can lower the live global/per-subject ceilings and Retry-After value
from Admin → Operations; the environment value remains the non-bypassable hard
ceiling.

Sandbox execution is identified by a job ID and supports explicit cancellation,
so Stop terminates the disposable container instead of only abandoning the HTTP
wait. The Docker broker remains the current executor, behind an interface that
can later be replaced by a Kubernetes executor without changing chat behavior.

File count and workspace size are separate controls. Admins can configure files
per upload and Code Interpreter workspace files independently (including 100
small text files), while the broker retains higher hard safety ceilings for
payload bytes, filenames, file count, artifacts, and runtime resources. Inputs
are rejected with an explicit workspace-limit error rather than silently
truncated.

Workspace and artifact filenames may use any script, so a generated
`report.pdf` (or the same name in another language) keeps its original
spelling through the sandbox, Media, and the download header. The shared
policy in `backend/app/sandbox/filenames.py` (mirrored in `sandbox/runner.py`)
rejects only path separators, control characters, BiDi and zero-width
formatting characters that disguise the real extension, hidden or
argument-looking names, and names over the character/UTF-8 byte budget. What a
file is allowed to be is still decided by the extension allowlist and the
per-artifact content validation.

### Image, video, and speech

Chat Tools can enable **image generation**, **video generation**, and **speech**
when the selected model and Connection support them. Image and video jobs reuse
the same auth, budget hold, SSRF, and media ACL path. Video runs as OpenRouter
async `/videos` work (`POST /api/videos/generate`, poll
`GET /api/videos/jobs/{id}`) for text-to-video and image-to-video (first-frame
reference). Provider polling URLs stay server-side; completed clips are stored
as `MediaAsset` (`kind=video`) and served with HTTP Range support.

## External clients

Alpharouter exposes `/v1` for clients that use the OpenAI API contract.
Chat completions are streaming-first: `POST /v1/chat/completions` requires
`stream=true`. Also available: `GET /v1/models` and `POST /v1/embeddings`.

- **Base URL:** `http://<alpha-router-host>:8080/v1`
- **Header:** `Authorization: Bearer <key>`

Two key types (plus an optional master key):

| Key | Created in | Spend | Typical use |
|---|---|---|---|
| Gateway API key (`alpha_router_...`) | Admin → API Keys | That key’s credit pool | Shared integrations, service accounts |
| Personal API key | Settings → API Key | The user’s monthly plan budget | One key per user for IDEs and scripts |
| Gateway master key | `GATEWAY_MASTER_KEY` in `.env` | The `gateway-service` account plan | Break-glass / platform automation |

Personal keys are self-service: one active key per user, shown in plaintext
only at creation, and visible in Activity and admin logs. Revoke before
rotating. Gateway keys may add connection and model allowlists; they inherit
the owner’s Public/Private catalog ACL and do not debit the owner’s personal
monthly budget.

Standard routes `/api` and `/v1` remain unchanged.

## Local development

Python 3.12 or newer is required. Prefer the Compose stack above for a full
environment. For a host-side backend/frontend loop:

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

**Frontend in a separate terminal:**

```bash
cd frontend
npm install
npx vite
```

The Vite development server proxies `/api` to `localhost:8080`.

## Tests

```bash
cd backend
pytest
```

```bash
cd frontend
npm test
npm run build
```

Final release verification also validates the resolved Compose model:

```bash
docker compose config --quiet
```

With a running, production-like stack and a scoped API key, run the
privacy-safe Agent gateway load gate. It sets `private_mode=true`,
`persist_chat=false`, never prints prompts/keys/response bodies, and exits
non-zero when the configured error-rate or P95 threshold fails:

```bash
cd backend
export ALPHAROUTER_API_KEY="alpha_router_..."
python tests/load/agent_gateway_load.py \
  --agent it-helpdesk \
  --model openrouter/auto \
  --concurrency 20 \
  --duration-seconds 60
```

Before production sign-off, also verify a denied Agent/Knowledge ACL, a revoked
document, an insufficient-evidence abstention, a prompt-injection case, stream
cancellation, dependency failure/recovery, and rollback to an evaluated version.

## In-app documentation

After login, documentation is available at:

- **Admin Guide:** `/admin/docs`
- **User Manual:** `/app/manual` or `/admin/manual`

## CI

`.gitlab-ci.yml` runs backend tests, frontend tests and production builds,
dependency audits, and container-image scanning.

## License

Alpharouter is released under the [MIT License](LICENSE).

**Alpharouter™**, Alpha Router, AlphaRouter, and the product logos are
trademarks of Majid Arasskhani. The MIT License does not grant trademark
rights. See [TRADEMARK.md](TRADEMARK.md) and [NOTICE](NOTICE).

Copyright © 2026 Majid Arasskhani.

Designed and developed by Majid Arasskhani.
Contact: Majid.Arasskhani@Gmail.com
