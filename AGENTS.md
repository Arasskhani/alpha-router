# Alpha Router — Agent Codebase Map

This map complements `CLAUDE.md`. Use `CLAUDE.md` for the detailed subsystem,
known-risk, and testing notes; this file records the canonical product and
technical names that agents must use.

## Product identity

- Display name: `Alpha Router`
- PascalCase: `AlphaRouter`
- snake_case: `alpha_router`
- kebab-case: `alpha-router`
- constant prefix: `ALPHA_ROUTER`
- API key prefix: `alpha_router_`
- gateway master key pattern: `sk-alpha-router-...`

External names such as OpenRouter, OpenAI, LiteLLM, PostgreSQL, Redis,
SeaweedFS, SAML, OIDC, and S3 remain unchanged. Standard routes `/api` and
`/v1` also remain unchanged.

## Repository map

```text
alpha-router/
├── backend/
│   ├── app/
│   │   ├── api/                 FastAPI routers
│   │   ├── models/              SQLAlchemy ORM models
│   │   ├── services/            application logic
│   │   ├── branding.py          canonical backend identity
│   │   ├── config.py            environment-backed settings
│   │   ├── database.py          async database sessions
│   │   ├── db_migrate.py        current-schema column/index patching
│   │   └── main.py              app factory, lifespan, SPA serving
│   └── tests/                   pytest tests using asyncio.run wrappers
├── frontend/
│   ├── src/                     React and TypeScript source
│   ├── public/                  static assets
│   └── dist/                    generated production bundle
├── docs/                        runbook, audits, and rename plan
├── sandbox/                     code-interpreter image
├── sandbox-broker/              broker image definition
├── deploy/seaweedfs/            pinned SeaweedFS support files
├── scripts/                     host operations scripts
├── docker-compose.yml
└── Dockerfile
```

## Runtime topology

Stage 8 uses the following deployment names.

```text
browser ──► alpha-router:8080
              ├─► pgbouncer:6432 ──► postgres:16
              ├─► redis:7
              ├─► seaweedfs:8333 (bucket: alpha-router-media)
              └─► alpha-router-sandbox-broker:8081
                    [network: alpha_router_sandbox_control, internal]
                        └─► docker.sock
                              └─► alpha-router-sandbox:latest
```

The PostgreSQL user and database are both `alpha_router`. Named volumes use
`alpha_router_pg`, `alpha_router_redis`, and `alpha_router_seaweedfs`.

## Authentication and gateway names

- Browser session cookie: `alpha_router_session`
- Browser CSRF cookie: `alpha_router_csrf`
- OIDC state cookie: `alpha_router_oidc_state`
- connector state cookie: `alpha_router_connector_state`
- Admin-issued gateway key prefix: `alpha_router_`
- OpenAI-compatible gateway routes: `/v1/*`
- Browser/API routes: `/api/*`

Example:

```bash
curl -sS "$ALPHA_ROUTER_BASE/v1/models" \
  -H "Authorization: Bearer $ALPHA_ROUTER_API_KEY"
```

## Data and frontend identifiers

- Gateway tables: `alpha_router_api_keys`,
  `alpha_router_api_key_audit_logs`
- Request-log foreign key: `alpha_router_api_key_id`
- Chat source: `alpha_router_chat`
- Export format: `alpha-router-chats`
- Wire markers: `__ALPHA_ROUTER_IMAGE_JSON__:`,
  `__ALPHA_ROUTER_IMAGE_PENDING__`,
  `__ALPHA_ROUTER_ATTACH_JSON__:`,
  `__ALPHA_ROUTER_AUDIO_JSON__:`
- Private media IndexedDB: `alpha_router_private_media`
- Cross-tab channel: `alpha_router_chat_sync`
- Leader lock: `alpha_router_chat_leader`
- Refresh event: `alpha_router_chat_refresh`

## Working conventions

- Put application logic in `backend/app/services/`.
- Commit database sessions explicitly in handlers.
- Add ORM columns to models; review data-shape changes explicitly.
- Route user-influenced outbound HTTP through the SSRF and bounded-I/O
  services.
- Encrypt stored secrets with `secret_crypto.encrypt_secret`.
- Route paid model calls through budget reservation and `log_usage`.
- Never rewrite provider pricing.
- Use Python 3.12 or newer.
- Run frontend development with `npx vite`; there is no `dev` package script.
- Do not commit or push unless the user explicitly asks.
