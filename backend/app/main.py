"""Alpha Router application entrypoint."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import admin, auth, authentication, chat, gateway, groups, images, logs, operations, plans, reports, smtp, user_chats, user_media, user_routes
from app.config import INSECURE_DEFAULTS, get_settings
from app.core.security import hash_password
from app.database import AsyncSessionLocal, Base, engine
from app.db_migrate import apply_schema_column_patches, run_one_time_migrations
from app.models.user import User
from app.services.auth_sync_scheduler import refresh_auth_sync_schedules
from app.services.bounded_io import RequestBodyLimitMiddleware
from app.services.csrf_protection import CsrfProtectionMiddleware
from app.services.scheduler import (
    refresh_chat_retention_cleanup_schedule,
    refresh_storage_cleanup_schedule,
    start_scheduler,
    stop_scheduler,
)
from app.services import object_storage_service as oss
from app.services.openrouter_image_service import close_openrouter_http_client
from app.services.proxy_service import configure_litellm_cache
from app.services.user_chat_storage_service import ensure_user_chat_store

settings = get_settings()


def resolve_frontend_dist(main_file: Path | None = None) -> Path:
    """Locate built React assets for Docker (/app/frontend/dist) or repo layout."""
    app_dir = (main_file or Path(__file__)).resolve().parent
    backend_root = app_dir.parent
    candidates = (
        backend_root / "frontend" / "dist",
        backend_root.parent / "frontend" / "dist",
    )
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[1]


_FRONTEND_DIST = resolve_frontend_dist()


def _assert_production_safe() -> None:
    """Refuse to start in production while known insecure defaults are configured.

    Env-gated: a no-op unless `settings.environment == "production"`. Existing
    dev/single-box deployments (which default to "development") boot unchanged.
    The guard checks externally exploitable application secrets, requires a
    strong LDAP bridge token when enabled, and requires the sandbox broker.
    """
    _check_production_safe(
        environment=settings.environment,
        secret_key=settings.secret_key,
        admin_password=settings.admin_password,
        gateway_master_key=settings.gateway_master_key,
        ldap_bridge_url=settings.ldap_bridge_url,
        ldap_bridge_token=settings.ldap_bridge_token,
        code_sandbox_broker_url=settings.code_sandbox_broker_url,
        code_sandbox_broker_token=settings.code_sandbox_broker_token,
    )


def _check_production_safe(
    *,
    environment: str,
    secret_key: str,
    admin_password: str,
    gateway_master_key: str,
    ldap_bridge_url: str = "",
    ldap_bridge_token: str = "",
    code_sandbox_broker_url: str = "",
    code_sandbox_broker_token: str = "",
) -> None:
    """Pure check used by the startup guard and by tests.

    Raises RuntimeError when production uses an insecure application secret or
    enables the LDAP bridge without a strong token, or lacks the authenticated
    sandbox broker. No-op in development.
    """
    if environment != "production":
        return
    insecure: list[str] = []
    if secret_key in INSECURE_DEFAULTS:
        insecure.append("SECRET_KEY")
    if admin_password in INSECURE_DEFAULTS:
        insecure.append("ADMIN_PASSWORD")
    if gateway_master_key in INSECURE_DEFAULTS:
        insecure.append("GATEWAY_MASTER_KEY")
    if ldap_bridge_url.strip():
        bridge_token = ldap_bridge_token.strip()
        if (
            not bridge_token
            or bridge_token in INSECURE_DEFAULTS
            or len(bridge_token) < 32
        ):
            insecure.append("LDAP_BRIDGE_TOKEN")
    if not code_sandbox_broker_url.strip():
        insecure.append("CODE_SANDBOX_BROKER_URL")
    if len(code_sandbox_broker_token.strip()) < 32:
        insecure.append("CODE_SANDBOX_BROKER_TOKEN")
    if insecure:
        raise RuntimeError(
            "Refusing to start in production with insecure default value(s): "
            + ", ".join(insecure)
            + ". Override each in your environment/.env before booting with ENVIRONMENT=production."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_production_safe()
    async with engine.begin() as conn:
        # Multiple uvicorn workers enter lifespan concurrently. Serialize DDL
        # discovery/creation so a newly introduced table cannot race in
        # PostgreSQL's type catalog and abort worker startup.
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(56023113)"))
        await conn.run_sync(Base.metadata.create_all)
    await apply_schema_column_patches()

    async with AsyncSessionLocal() as db:
        admin_user = (await db.execute(select(User).where(User.username == settings.admin_username))).scalars().first()
        if not admin_user:
            from app.services.rbac import bootstrap_super_admin_role_slugs, primary_role_slug

            bootstrap_roles = bootstrap_super_admin_role_slugs()
            db.add(
                User(
                    username=settings.admin_username,
                    email="admin@alpha-router.local",
                    display_name="Administrator",
                    hashed_password=hash_password(settings.admin_password),
                    role=primary_role_slug(bootstrap_roles),
                    auth_provider="local",
                )
            )
            await db.flush()
            admin_user = (await db.execute(select(User).where(User.username == settings.admin_username))).scalars().first()
            if admin_user:
                from app.models.user import UserRoleAssignment

                for slug in bootstrap_roles:
                    db.add(UserRoleAssignment(user_id=admin_user.id, role_slug=slug))
            await db.commit()

    async with AsyncSessionLocal() as db:
        await asyncio.to_thread(oss.ensure_bucket)
        await run_one_time_migrations(db)
        from app.services.user_role_service import ensure_super_admin_roles

        for row in (await db.execute(select(User))).scalars().all():
            await ensure_super_admin_roles(db, row, admin_username=settings.admin_username)
            await ensure_user_chat_store(db, row.id)  # ensures user_chat_prefs row
        await db.commit()

    start_scheduler()
    await refresh_storage_cleanup_schedule()
    await refresh_chat_retention_cleanup_schedule()
    await refresh_auth_sync_schedules()
    configure_litellm_cache()
    yield
    stop_scheduler()
    await close_openrouter_http_client()
    await engine.dispose()


app = FastAPI(title="Alpha Router Organizational AI Platform", version="1.0.0", lifespan=lifespan)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers to every response.

    HSTS is only emitted when ``ENABLE_HSTS=true`` AND ``ENVIRONMENT=production``
    (i.e. the deployment is behind HTTPS). CSP is opt-in via
    ``CONTENT_SECURITY_POLICY`` — empty by default to avoid breaking the SPA
    without testing. The remaining headers are safe-by-default and applied to
    all responses regardless of environment.
    """

    _BASE_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in self._BASE_HEADERS.items():
            response.headers.setdefault(key, value)
        settings = get_settings()
        if getattr(settings, "enable_hsts", False) and getattr(settings, "environment", "development") == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        csp = (getattr(settings, "content_security_policy", "") or "").strip()
        if csp:
            response.headers.setdefault("Content-Security-Policy", csp)
        return response


app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://127.0.0.1:8080", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-Client-App",
        settings.csrf_header_name,
    ],
)
app.add_middleware(CsrfProtectionMiddleware)

app.include_router(auth.router)
app.include_router(gateway.router)
app.include_router(admin.router)
app.include_router(user_routes.router)
app.include_router(user_media.router)
app.include_router(user_chats.router)
app.include_router(user_chats.messages_router)
app.include_router(images.router)
app.include_router(operations.router)
app.include_router(plans.router)
app.include_router(reports.router)
app.include_router(logs.router)
app.include_router(authentication.router)
app.include_router(smtp.router)
app.include_router(groups.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    routes = [getattr(r, "path", None) for r in app.routes]
    return {
        "status": "ok",
        "service": "alpha-router",
        "frontend_built": _FRONTEND_DIST.is_dir(),
        "connections_list_api": any(
            getattr(r, "path", "") == "/api/admin/connections" and "GET" in getattr(r, "methods", set())
            for r in app.routes
        ),
    }


def _fallback_html() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><title>Alpha Router</title></head>
<body style="font-family:system-ui;max-width:640px;margin:3rem auto;padding:1rem">
  <h1>Alpha Router UI not built yet</h1>
  <p>Run from the project folder:</p>
  <pre>cd frontend\nnpm install\nnpm run build</pre>
  <p>Rebuild the Docker image so the frontend is compiled into the container:</p>
  <pre>docker compose up --build -d</pre>
  <p>API docs: <a href="/docs">/docs</a> · Health: <a href="/health">/health</a></p>
</body></html>"""


# 16x16 transparent PNG embedded in ICO — empty tab icon
_EMPTY_FAVICON_ICO = (
    b"\x00\x00\x01\x00\x01\x00\x10\x10\x00\x00\x01\x00 \x00K\x00"
    b"\x00\x00\x16\x00\x00\x00\x89PNG\r\n\x1a\n\x00\x00"
    b"\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06"
    b"\x00\x00\x00\x1f\xf3\xffa\x00\x00\x00\x12IDATx"
    b"\xdac`\x18\x05\xa3`\x14\x8c\x02\x08\x00\x00\x04\x10\x00"
    b"\x01\xafE\x88,\x00\x00\x00\x00IEND\xaeB`"
    b"\x82"
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Empty favicon — avoid SPA fallback serving index.html as tab icon."""
    icon = _FRONTEND_DIST / "favicon.ico"
    body = icon.read_bytes() if icon.is_file() else _EMPTY_FAVICON_ICO
    return Response(
        content=body,
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/")
async def root():
    index = _FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(_fallback_html())


# Static assets (JS/CSS) — must be after explicit routes like /health
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """React Router: serve index.html for client-side routes (never shadow /api — those are separate routes)."""
        # Never let the SPA mask unmatched API/gateway paths — return JSON 404
        # so API clients get a predictable error instead of the HTML shell.
        if full_path.startswith(("api/", "v1/", "health", "docs", "openapi.json", "redoc")):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found", "path": f"/{full_path}"},
            )
        # Path-traversal containment: resolve the requested path and confirm it
        # stays within the frontend dist directory before serving it. Without
        # this, a request like /../../etc/passwd could escape dist via the
        # {full_path:path} converter and read arbitrary container files.
        dist_root = _FRONTEND_DIST.resolve()
        candidate = (_FRONTEND_DIST / full_path).resolve()
        try:
            candidate.relative_to(dist_root)
        except ValueError:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if candidate.is_file():
            return FileResponse(candidate)
        index = _FRONTEND_DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(_fallback_html(), status_code=404)
