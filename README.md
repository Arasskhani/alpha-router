# Alpharouter — Organizational AI Control Plane

Alpharouter is an organizational AI control plane with a built-in web UI. It
connects teams to upstream LLM providers such as OpenRouter, OpenAI, Anthropic,
Google, and xAI while enforcing budgets, RBAC, quotas, retention, and audit
logging.

The platform provides:

- **User app** (`/app`) — chat, media library, and activity
- **Admin panel** (`/admin`) — identity, access, budgets, providers, models,
  reports, operations, storage, Agents, Knowledge, and evaluations
- **OpenAI-compatible gateway** (`/v1`) — API-key access for external tools
  and automation

Alpharouter is OS-independent. Develop on any host with Docker available, and
run the same Compose stack on Linux or any other Docker-capable environment.

## Quick start with Docker

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
| SeaweedFS S3 API | http://localhost:8333 |
| SeaweedFS admin UI | http://localhost:23646 |

Bootstrap administrator credentials come from `ADMIN_USERNAME` and
`ADMIN_PASSWORD` in `.env`. Replace every example secret before production use,
including `SECRET_KEY`, `DATA_ENCRYPTION_KEY`, `GATEWAY_MASTER_KEY`,
`SANDBOX_BROKER_TOKEN`, database and Redis passwords, and S3/SeaweedFS
credentials.

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
├── deploy/           SeaweedFS support files
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

## Configuration

Copy `.env.example` to `.env`. Important groups include:

- **Database and cache** — `DATABASE_URL`, optional `DATABASE_READ_URL`, pool
  limits, worker count, rate limits, and `REDIS_URL`
- **Authentication** — local accounts plus optional LDAP, SAML, OIDC, and TOTP
- **Storage** — SeaweedFS through its S3-compatible API using `S3_*` settings
- **Gateway** — `GATEWAY_MASTER_KEY` and administrator-issued
  `alpha_router_...` API keys
- **Public URLs** — `API_PUBLIC_URL` and `FRONTEND_URL`
- **Sandbox** — broker URL, token, timeout, and resource limits
- **Agents & Knowledge** — Qdrant, worker, retrieval, evaluation, observability,
  and the built-in specialist bootstrap

For production, set `ENVIRONMENT=production` and keep
`PRODUCTION_GUARD_MODE=hard-fail`.

### Agents & Knowledge

Alpharouter includes five system specialist Agents: IT Helpdesk, HR Assistant,
Legal Consultant, Finance Consultant, and Marketing Consultant. Startup creates
them idempotently with immutable initial versions, bounded policies, bilingual
FA/EN routing hints and disclaimers, one domain Knowledge Base each, and a
100-case draft golden evaluation dataset each.

The Knowledge Bases are intentionally empty. System bootstrap never treats
sample text as authoritative organization policy and never bypasses document
review, release indexing, or evaluation approval. HR, Legal, and Finance Agents
and their Knowledge Bases default to private; IT and Marketing default to
public/internal. Configure the defaults with:

```dotenv
SEED_SPECIALIST_AGENTS_ENABLED=true
SEED_AGENT_PRIMARY_MODEL_ID=openrouter/auto
```

Production activation workflow:

1. Configure the Agent and Knowledge ACLs in **Admin → Agents & Knowledge**,
   then complete Knowledge-owner and (for sensitive domains) independent domain
   approval for the seeded binding.
2. Upload authoritative documents; wait for malware, parser, and injection
   checks; approve each revision with a different reviewer.
3. Create a Knowledge release, submit it with a different publisher, and wait
   for the Qdrant index to become active.
4. Replace every `curate:` sentinel in the seeded golden set with real immutable
   document-version IDs and review all prompts.
5. Activate the dataset, execute the deterministic evaluation, complete human
   review when required, and only then publish a replacement Agent version.

Seeded bindings remain pending and cannot retrieve until their maker-checker
approvals complete. If the bound Agent version is already active, the final
approval publishes only the binding authorization; it does not bypass document
review or release indexing. Active golden datasets become publish gates; draft
seed datasets do not block initial bootstrap.

Operational endpoints:

- `GET /health` and `GET /ready` — process and dependency health
- `GET /metrics` — bounded Prometheus metrics (Bearer-protected in production)
- `/admin/agents`, `/admin/knowledge`, `/admin/agent-evaluations` — governance
  and quality control surfaces

Use private mode for non-persistent conversations. Private mode disables
sensitive Knowledge retrieval and memory according to Agent policy; it is not a
way to bypass ACL, budget, audit, or provider-egress controls.

### Code Interpreter model compatibility

Compatibility with the Code Interpreter tool is measured per connection and
model instead of being hardcoded per vendor, so new models need no code change.
A scheduled job probes due models in small claimed batches (Python block →
sandbox execution → artifact → follow-up turn), and real chat turns feed the
same registry. Repeated hard failures such as `MALFORMED_FUNCTION_CALL`
quarantine a model, transient provider errors do not. Verified and blocked
models also shape OpenRouter Auto Router constraints per request. Administrators
can review evidence, probe on demand, or pin a decision from
Admin → Models → Code Interpreter.

### Video generation

Chat Tools → **Video Generation** runs OpenRouter async `/videos` jobs
(`POST /api/videos/generate`, poll `GET /api/videos/jobs/{id}`). Text-to-video
and image-to-video (first-frame reference) reuse the same auth, budget hold,
SSRF, and media ACL path as image generation. Provider polling URLs stay
server-side; completed clips are stored as `MediaAsset` (`kind=video`) and
served with HTTP Range support.

### Code Interpreter capacity and workspace

Code Interpreter turns use a Redis-backed lease shared by all API workers.
The default admission ceiling is 200 end-to-end turns, with a separate
per-user/API-key ceiling. Requests above capacity are rejected before provider
or budget reservation work with HTTP `429` and `Retry-After`; Redis outages fail
closed for this feature.
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
`گزارش-مدیریتی.pdf` keeps its name through the sandbox, Media, and the download
header. The shared policy in `backend/app/sandbox/filenames.py` (mirrored in
`sandbox/runner.py`) rejects only path separators, control characters, BiDi and
zero-width formatting characters that disguise the real extension, hidden or
argument-looking names, and names over the character/UTF-8 byte budget. What a
file is allowed to be is still decided by the extension allowlist and the
per-artifact content validation.

## External clients

Alpharouter exposes `/v1` for clients that use the OpenAI API contract:

- **Base URL:** `http://<alpha-router-host>:8080/v1`
- **API key:** an `alpha_router_...` key created under Admin → API Keys

Standard routes `/api` and `/v1` remain unchanged.

## Local development

Python 3.12 or newer is required. Prefer the Compose stack above for a full
environment. For a host-side backend/frontend loop:

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
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

Internal IT project; apply the license required by your organization.
