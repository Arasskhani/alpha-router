# Alpha Router — Organizational AI Platform

Alpha Router is an organizational AI control plane with a built-in web UI. It connects teams to upstream LLM providers (OpenRouter, OpenAI, Anthropic, Google, and others) while enforcing budgets, roles, plans, and audit logging.

The platform includes:

- **User app** (`/app`) — chat, media library, usage & activity, recommendations
- **Admin panel** (`/admin`) — users, groups, roles, plans, connections, models, API keys, reports, operations, storage
- **OpenAI-compatible API** (`/v1`) — optional gateway for external tools (IDE extensions, scripts, automation) using the same models and budgets

## Quick start (Docker)

Start **Docker Desktop**, then:

```powershell
cd path\to\Alpha Router
Copy-Item .env.example .env
.\scripts\start-docker.ps1
```

Or manually:

```powershell
docker compose up --build -d
```

### Endpoints

| Service | URL |
|--------|-----|
| UI + API | http://localhost:8080 |
| Health | http://localhost:8080/health |
| MinIO console | http://localhost:9001 (`alpha-router` / `***REMOVED***`) |
| PostgreSQL | localhost:5432 (`alpha-router` / `alpha-router`) |

Default **admin panel** login: `admin` / `admin`

Before production use, change `SECRET_KEY`, admin passwords, `GATEWAY_MASTER_KEY`, and MinIO/S3 credentials in `.env` (see `.env.example`).

### Stop the stack

```powershell
.\scripts\stop-all.ps1
```

Stops Docker Compose services (app, PostgreSQL, Redis, MinIO) and the optional Windows LDAP bridge on port 8765.

## Project structure

```
Alpha Router/
├── backend/          FastAPI app (API, gateway, LDAP/Keycloak sync, migrations)
├── frontend/         React SPA (admin panel + user app)
├── scripts/          start-docker.ps1, stop-all.ps1, start-ldap-bridge.ps1
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

## Configuration

Copy `.env.example` to `.env`. Key settings:

- **Database / cache** — `DATABASE_URL` (via PgBouncer in Docker Compose), optional `DATABASE_READ_URL`, `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT`, `UVICORN_WORKERS`, chat rate limits (`CHAT_*_RATE_LIMIT_PER_MIN`), `REDIS_URL`
- **Auth** — local admin account; optional LDAP and Keycloak (see Admin → Authentication)
- **Storage** — MinIO/S3 for media (`S3_*`, `MEDIA_CDN_PREFIX`)
- **Gateway** — `GATEWAY_MASTER_KEY` for OpenAI-compatible `/v1` access
- **Public URLs** — `API_PUBLIC_URL`, `FRONTEND_URL`

### LDAP on Windows (optional)

For signed Active Directory from Docker, run the host LDAP bridge on Windows:

```powershell
.\scripts\start-ldap-bridge.ps1
```

The app container expects `LDAP_BRIDGE_URL=http://host.docker.internal:8765` (already set in `docker-compose.yml`).

## External clients (OpenAI-compatible API)

Alpha Router exposes `/v1` for tools that speak the OpenAI API. Configure the client with:

- **Base URL:** `http://<alpha-router-host>:8080/v1`
- **API key:** a Alpha Router API key from Admin → API Keys (admin gateway key or per-user key)

Pass the end-user identity in the `user` field when the client supports it so budgets and logs attribute usage correctly.

The built-in chat UI uses JWT session auth on `/api/*` and does not require this setup.

## Local development

**Backend:**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

**Frontend** (separate terminal):

```powershell
cd frontend
npm install
npm run dev
```

Run PostgreSQL, Redis, and MinIO via Docker Compose or point `.env` at existing services. The production Docker image builds the frontend into `frontend/dist` and serves it from FastAPI.

**Tests:**

```powershell
cd backend
pytest
```

## Documentation

In-app guides (after login):

- **Admin Guide** — `/admin/docs`
- **User Manual** — `/app/manual` or `/admin/manual`

## GitLab CI

`.gitlab-ci.yml` runs a backend import check and builds the Docker image on branch pushes.

## License

Internal IT project — adjust license as required by your organization.
# Alpha Router
