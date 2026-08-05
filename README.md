# Alpha Router — Organizational AI Control Plane

Alpha Router is an organizational AI control plane with a built-in web UI. It
connects teams to upstream LLM providers such as OpenRouter, OpenAI, Anthropic,
Google, and xAI while enforcing budgets, RBAC, quotas, retention, and audit
logging.

The platform provides:

- **User app** (`/app`) — chat, media library, and activity
- **Admin panel** (`/admin`) — identity, access, budgets, providers, models,
  reports, operations, and storage
- **OpenAI-compatible gateway** (`/v1`) — API-key access for external tools,
  scripts, and automation

## Quick start with Docker

Start Docker Desktop, then:

```powershell
cd path\to\alpha-router
Copy-Item .env.example .env
.\scripts\start-docker.ps1
```

Or start Compose directly:

```powershell
docker compose up --build -d
```

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

```powershell
.\scripts\stop-all.ps1
```

This stops the Compose services and the optional Windows LDAP bridge.

## Project structure

```text
alpha-router/
├── backend/          FastAPI application, gateway, schedulers, and services
├── frontend/         React and Vite single-page application
├── sandbox/          Isolated code-interpreter image
├── sandbox-broker/   Internal Docker sandbox controller
├── deploy/           SeaweedFS support files
├── scripts/          Windows host operations scripts
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

For production, set `ENVIRONMENT=production` and keep
`PRODUCTION_GUARD_MODE=hard-fail`.

## External clients

Alpha Router exposes `/v1` for clients that use the OpenAI API contract:

- **Base URL:** `http://<alpha-router-host>:8080/v1`
- **API key:** an `alpha_router_...` key created under Admin → API Keys

Standard routes `/api` and `/v1` remain unchanged.

## Local development

Python 3.12 or newer is required.

**Backend:**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

**Frontend in a separate terminal:**

```powershell
cd frontend
npm install
npx vite
```

The Vite development server proxies `/api` to `localhost:8080`.

## Tests

```powershell
cd backend
pytest
```

```powershell
cd frontend
npm test
npm run build
```

## Documentation

After login, documentation is available at:

- **Admin Guide:** `/admin/docs`
- **User Manual:** `/app/manual` or `/admin/manual`

Operational and security documentation is also available under `docs/`.

## CI

`.gitlab-ci.yml` runs backend tests, frontend tests and production builds,
dependency audits, and container-image scanning.

## License

Internal IT project; apply the license required by your organization.
