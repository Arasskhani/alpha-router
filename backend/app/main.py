"""Alpharouter application entrypoint."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from app.api import admin, auth, authentication, chat, gateway, groups, images, logs, operations, plans, reports, smtp, user_chats, user_media, user_routes, user_settings
from app.branding import (
    APPLICATION_TITLE,
    CSRF_COOKIE_NAME,
    DEFAULT_ADMIN_EMAIL,
    INTERNAL_DOMAIN,
    LOGGER_NAMESPACE,
    PRODUCT_NAME,
    PRODUCT_SLUG,
    SESSION_COOKIE_NAME,
)
from app.config import INSECURE_DEFAULTS, get_settings
from app.core.security import hash_password
from app.database import AsyncSessionLocal, Base, engine
from app.db_migrate import apply_schema_column_patches, validate_accounting_schema
from app.legacy_brand_denylist import (
    LEGACY_CSRF_COOKIE_NAMES,
    LEGACY_DATABASE_URLS,
    LEGACY_SESSION_COOKIE_NAMES,
)
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
from app.services.security_headers import SecurityHeadersMiddleware
from app.services.docs_guard import OpenApiDocsGuardMiddleware
from app.services.observability import increment
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
    requires the sandbox broker,
    requires Redis auth, a dedicated data-encryption key, admin-only OpenAPI
    docs, and secure transport settings. Behavior is controlled by
    `production_guard_mode`: "hard-fail" (default) raises RuntimeError;
    "warning" logs and continues for temporary migrations.
    """
    _check_production_safe(
        environment=settings.environment,
        secret_key=settings.secret_key,
        admin_password=settings.admin_password,
        service_admin_password=settings.service_admin_password,
        gateway_master_key=settings.gateway_master_key,
        code_sandbox_broker_url=settings.code_sandbox_broker_url,
        code_sandbox_broker_token=settings.code_sandbox_broker_token,
        redis_url=settings.redis_url,
        redis_password=settings.redis_password,
        data_encryption_key=settings.data_encryption_key,
        openapi_admin_only=settings.openapi_admin_only,
        database_url=settings.database_url,
        saml_enabled=settings.saml_enabled,
        oidc_enabled=settings.oidc_enabled,
        oidc_issuer=settings.oidc_issuer,
        smtp_host=settings.smtp_host,
        smtp_tls=settings.smtp_tls,
        s3_endpoint_url=settings.s3_endpoint_url,
        s3_use_ssl=settings.s3_use_ssl,
        frontend_url=settings.frontend_url,
        api_public_url=settings.api_public_url,
        enable_hsts=settings.enable_hsts,
        allow_insecure_code_subprocess=settings.allow_insecure_code_subprocess,
        s3_access_key=settings.s3_access_key,
        s3_secret_key=settings.s3_secret_key,
        allow_legacy_bearer_auth=settings.allow_legacy_bearer_auth,
        session_cookie_name=settings.session_cookie_name,
        csrf_cookie_name=settings.csrf_cookie_name,
        guard_mode=settings.production_guard_mode,
    )


def collect_dangerous_opt_in_flags(
    *,
    allow_legacy_bearer_auth: bool = False,
    allow_ssrf_private_ranges: bool = False,
    allow_insecure_code_subprocess: bool = False,
) -> list[tuple[str, str]]:
    """Return (env_name, reason) for dangerous escape-hatch flags that are on.

    Defaults are false; enabling any of these weakens CSRF, SSRF, or sandbox
    isolation. Used for loud startup warnings (does not block boot in development).
    """
    enabled: list[tuple[str, str]] = []
    if allow_legacy_bearer_auth:
        enabled.append(
            (
                "ALLOW_LEGACY_BEARER_AUTH",
                "browser Bearer JWT bypasses the HttpOnly session cookie + CSRF path; "
                "use /v1 API keys for machine clients instead",
            )
        )
    if allow_ssrf_private_ranges:
        enabled.append(
            (
                "ALLOW_SSRF_PRIVATE_RANGES",
                "ssrf_guard allows private/loopback/metadata targets; prefer SAML "
                "Metadata XML upload or a public proxy URL for internal resources",
            )
        )
    if allow_insecure_code_subprocess:
        enabled.append(
            (
                "ALLOW_INSECURE_CODE_SUBPROCESS",
                "code interpreter may run on the API host via subprocess in development; "
                "prefer CODE_SANDBOX_BROKER_URL + SANDBOX_BROKER_TOKEN",
            )
        )
    return enabled


def _warn_dangerous_opt_in_flags() -> None:
    """Log a clear warning for each dangerous opt-in flag that is enabled."""
    for name, reason in collect_dangerous_opt_in_flags(
        allow_legacy_bearer_auth=settings.allow_legacy_bearer_auth,
        allow_ssrf_private_ranges=settings.allow_ssrf_private_ranges,
        allow_insecure_code_subprocess=settings.allow_insecure_code_subprocess,
    ):
        logging.getLogger(LOGGER_NAMESPACE).warning(
            "Dangerous opt-in enabled: %s — %s. Leave this false outside an isolated lab.",
            name,
            reason,
        )


def _redis_url_has_password(redis_url: str, *, redis_password: str = "") -> bool:
    """True when the Redis connection URL carries an inline password.

    Accepts redis/rediss schemes. A separately-configured `redis_password`
    also satisfies the check (Phase 9 rebuilds the URL with it).
    """
    if redis_password.strip() and redis_password.strip() not in INSECURE_DEFAULTS:
        return True
    url = (redis_url or "").strip()
    if not url:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"redis", "rediss"}
        and bool(parsed.password)
        and parsed.password not in INSECURE_DEFAULTS
    )


def _url_uses_tls(url: str) -> bool:
    """Return whether a configured URL uses an encrypted transport."""
    try:
        return urlsplit((url or "").strip()).scheme in {"https", "rediss"}
    except ValueError:
        return False


def _url_is_loopback(url: str) -> bool:
    """True for localhost / loopback browser URLs used by single-box installs."""
    try:
        host = (urlsplit((url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}


def _url_host_is_internal(url: str) -> bool:
    """True for loopback or single-label Docker Compose service hostnames."""
    try:
        host = (urlsplit((url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    # Compose service names are single DNS labels (e.g. seaweedfs, redis).
    return "." not in host


def _url_has_secure_password(url: str) -> bool:
    """Return whether a configured URL contains a non-placeholder password."""
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return False
    return bool(parsed.password and parsed.password not in INSECURE_DEFAULTS)


def _collect_production_insecurities(
    *,
    environment: str,
    secret_key: str,
    admin_password: str,
    service_admin_password: str = "",
    gateway_master_key: str = "",
    code_sandbox_broker_url: str = "",
    code_sandbox_broker_token: str = "",
    redis_url: str = "",
    redis_password: str = "",
    data_encryption_key: str = "",
    openapi_admin_only: bool = False,
    database_url: str = "",
    saml_enabled: bool = False,
    oidc_enabled: bool = False,
    oidc_issuer: str = "",
    smtp_host: str = "",
    smtp_tls: bool = True,
    s3_endpoint_url: str = "",
    s3_use_ssl: bool = True,
    frontend_url: str = "",
    api_public_url: str = "",
    enable_hsts: bool = True,
    allow_insecure_code_subprocess: bool = False,
    s3_access_key: str = "",
    s3_secret_key: str = "",
    allow_legacy_bearer_auth: bool = False,
    session_cookie_name: str = SESSION_COOKIE_NAME,
    csrf_cookie_name: str = CSRF_COOKIE_NAME,
) -> list[str]:
    """Pure collector used by the startup guard and by tests.

    Returns the list of insecure-default names when production uses an insecure
    application secret, lacks the authenticated sandbox broker, runs Redis
    without a password, lacks a dedicated data-encryption key, or exposes
    OpenAPI docs to non-admins. Returns an empty list in development.

    Loopback HTTP frontend/API URLs and Compose-internal object storage are
    accepted for single-box / internal deployments; non-loopback cleartext and
    legacy browser Bearer auth are still rejected.
    """
    if environment != "production":
        return []
    insecure: list[str] = []
    if secret_key in INSECURE_DEFAULTS:
        insecure.append("SECRET_KEY")
    if admin_password in INSECURE_DEFAULTS:
        insecure.append("ADMIN_PASSWORD")
    if service_admin_password in INSECURE_DEFAULTS:
        insecure.append("SERVICE_ADMIN_PASSWORD")
    if gateway_master_key in INSECURE_DEFAULTS:
        insecure.append("GATEWAY_MASTER_KEY")
    if not code_sandbox_broker_url.strip():
        insecure.append("CODE_SANDBOX_BROKER_URL")
    if len(code_sandbox_broker_token.strip()) < 32:
        insecure.append("CODE_SANDBOX_BROKER_TOKEN")
    if not _redis_url_has_password(redis_url, redis_password=redis_password):
        insecure.append("REDIS_PASSWORD")
    if not data_encryption_key.strip() or data_encryption_key in INSECURE_DEFAULTS:
        insecure.append("DATA_ENCRYPTION_KEY")
    if not openapi_admin_only:
        insecure.append("OPENAPI_DOCS")
    if database_url in {
        "postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router",
        "postgresql+asyncpg://alpha_router:changeme@pgbouncer:6432/alpha_router",
    } | LEGACY_DATABASE_URLS or (
        database_url.strip() and not _url_has_secure_password(database_url)
    ):
        insecure.append("DATABASE_URL")
    # SAML ACS/metadata are derived from api_public_url; require HTTPS when enabled.
    if saml_enabled and api_public_url.strip() and (
        not _url_uses_tls(api_public_url) and not _url_is_loopback(api_public_url)
    ):
        insecure.append("SAML_TLS")
    if oidc_enabled and (
        (oidc_issuer.strip() and not _url_uses_tls(oidc_issuer))
        or (
            api_public_url.strip()
            and not _url_uses_tls(api_public_url)
            and not _url_is_loopback(api_public_url)
        )
    ):
        insecure.append("OIDC_TLS")
    if smtp_host.strip() and not smtp_tls:
        insecure.append("SMTP_TLS")
    if (
        s3_endpoint_url.strip()
        and not s3_use_ssl
        and not _url_host_is_internal(s3_endpoint_url)
    ):
        insecure.append("S3_TLS")
    if s3_access_key in INSECURE_DEFAULTS or s3_secret_key in INSECURE_DEFAULTS:
        insecure.append("S3_CREDENTIALS")
    if (
        frontend_url.strip()
        and not _url_uses_tls(frontend_url)
        and not _url_is_loopback(frontend_url)
    ):
        insecure.append("FRONTEND_TLS")
    if (
        api_public_url.strip()
        and not _url_uses_tls(api_public_url)
        and not _url_is_loopback(api_public_url)
    ):
        insecure.append("API_PUBLIC_TLS")
    public_surface = any(
        url.strip() and not _url_is_loopback(url)
        for url in (frontend_url, api_public_url)
    )
    if public_surface and not enable_hsts:
        insecure.append("HSTS")
    if allow_insecure_code_subprocess:
        insecure.append("INSECURE_CODE_SUBPROCESS")
    if allow_legacy_bearer_auth:
        insecure.append("LEGACY_BEARER_AUTH")
    if session_cookie_name in LEGACY_SESSION_COOKIE_NAMES:
        insecure.append("SESSION_COOKIE_NAME")
    if csrf_cookie_name in LEGACY_CSRF_COOKIE_NAMES:
        insecure.append("CSRF_COOKIE_NAME")
    return insecure


def _check_production_safe(
    *,
    environment: str,
    secret_key: str,
    admin_password: str,
    service_admin_password: str = "",
    gateway_master_key: str = "",
    code_sandbox_broker_url: str = "",
    code_sandbox_broker_token: str = "",
    redis_url: str = "",
    redis_password: str = "",
    data_encryption_key: str = "",
    openapi_admin_only: bool = False,
    database_url: str = "",
    saml_enabled: bool = False,
    oidc_enabled: bool = False,
    oidc_issuer: str = "",
    smtp_host: str = "",
    smtp_tls: bool = True,
    s3_endpoint_url: str = "",
    s3_use_ssl: bool = True,
    frontend_url: str = "",
    api_public_url: str = "",
    enable_hsts: bool = True,
    allow_insecure_code_subprocess: bool = False,
    s3_access_key: str = "",
    s3_secret_key: str = "",
    allow_legacy_bearer_auth: bool = False,
    session_cookie_name: str = SESSION_COOKIE_NAME,
    csrf_cookie_name: str = CSRF_COOKIE_NAME,
    guard_mode: str = "hard-fail",
) -> None:
    """Pure check used by the startup guard and by tests.

    Collects insecure defaults and, when any are present, either logs a warning
    (`guard_mode="warning"`) and returns, or raises RuntimeError
    (`guard_mode="hard-fail"`, the default for backward compatibility). No-op
    in development.
    """
    insecure = _collect_production_insecurities(
        environment=environment,
        secret_key=secret_key,
        admin_password=admin_password,
        service_admin_password=service_admin_password,
        gateway_master_key=gateway_master_key,
        code_sandbox_broker_url=code_sandbox_broker_url,
        code_sandbox_broker_token=code_sandbox_broker_token,
        redis_url=redis_url,
        redis_password=redis_password,
        data_encryption_key=data_encryption_key,
        openapi_admin_only=openapi_admin_only,
        database_url=database_url,
        saml_enabled=saml_enabled,
        oidc_enabled=oidc_enabled,
        oidc_issuer=oidc_issuer,
        smtp_host=smtp_host,
        smtp_tls=smtp_tls,
        s3_endpoint_url=s3_endpoint_url,
        s3_use_ssl=s3_use_ssl,
        frontend_url=frontend_url,
        api_public_url=api_public_url,
        enable_hsts=enable_hsts,
        allow_insecure_code_subprocess=allow_insecure_code_subprocess,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        allow_legacy_bearer_auth=allow_legacy_bearer_auth,
        session_cookie_name=session_cookie_name,
        csrf_cookie_name=csrf_cookie_name,
    )
    if not insecure:
        return
    message = (
        "Refusing to start in production with insecure default value(s): "
        + ", ".join(insecure)
        + ". Override each in your environment/.env before booting with ENVIRONMENT=production."
    )
    if guard_mode == "warning":
        increment("production_guard_warning")
        _PRODUCTION_GUARD_LOG.warning(
            "Production guard warning (non-blocking): %s", message
        )
        return
    raise RuntimeError(message)


_PRODUCTION_GUARD_LOG = logging.getLogger(f"{LOGGER_NAMESPACE}.production_guard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_production_safe()
    _warn_dangerous_opt_in_flags()
    async with engine.begin() as conn:
        # Multiple uvicorn workers enter lifespan concurrently. Serialize DDL
        # discovery/creation so a newly introduced table cannot race in
        # PostgreSQL's type catalog and abort worker startup.
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(56023113)"))
        await conn.run_sync(Base.metadata.create_all)
    await apply_schema_column_patches()
    await validate_accounting_schema()

    async with AsyncSessionLocal() as db:
        from app.services.username_norm import find_user_by_username_ci, normalize_username

        # Every Uvicorn worker enters lifespan concurrently. Serialize the
        # check-and-create bootstrap transaction so a fresh database cannot
        # race on the unique username/email indexes.
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(56023114)"))
        admin_username = normalize_username(settings.admin_username) or settings.admin_username.strip()
        admin_user = await find_user_by_username_ci(db, admin_username)
        if not admin_user:
            # A seed admin may already exist under a previous ADMIN_USERNAME.
            # Reuse it by current or legacy bootstrap email instead of creating
            # a duplicate administrator.
            admin_user = (
                await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
            ).scalars().first()
        if not admin_user:
            legacy_admin_emails = (
                "alpharouter@alpharouter.ent",
                f"admin@{INTERNAL_DOMAIN}",
            )
            for legacy_admin_email in legacy_admin_emails:
                admin_user = (
                    await db.execute(select(User).where(User.email == legacy_admin_email))
                ).scalars().first()
                if admin_user:
                    admin_user.email = DEFAULT_ADMIN_EMAIL
                    break
        if not admin_user:
            from app.services.rbac import bootstrap_super_admin_role_slugs

            bootstrap_roles = bootstrap_super_admin_role_slugs()
            db.add(
                User(
                    username=admin_username,
                    email=DEFAULT_ADMIN_EMAIL,
                    display_name="Administrator",
                    hashed_password=hash_password(settings.admin_password),
                    auth_provider="local",
                )
            )
            await db.flush()
            admin_user = await find_user_by_username_ci(db, admin_username)
            if admin_user:
                from app.models.user import UserRoleAssignment

                for slug in bootstrap_roles:
                    db.add(UserRoleAssignment(user_id=admin_user.id, role_slug=slug))
        await db.commit()

    async with AsyncSessionLocal() as db:
        await asyncio.to_thread(oss.ensure_bucket)
        from app.services.user_role_service import ensure_super_admin_roles

        for row in (await db.execute(select(User))).scalars().all():
            await ensure_super_admin_roles(db, row, admin_username=settings.admin_username)
            await ensure_user_chat_store(db, row.id)  # ensures user_chat_prefs row
        await db.commit()

    async with AsyncSessionLocal() as db:
        from app.services.transfer_limits_service import get_transfer_limits

        await get_transfer_limits(db)
        from app.services.code_interpreter_capacity_service import (
            sync_code_interpreter_capacity_policy,
        )

        try:
            await sync_code_interpreter_capacity_policy(db)
        except HTTPException:
            logging.getLogger(LOGGER_NAMESPACE).warning(
                "Code Interpreter capacity policy could not be published; "
                "Code Interpreter admission will fail closed until Redis recovers."
            )
        from app.services.model_tool_compatibility_service import (
            ensure_all_model_compatibility_rows,
        )

        await ensure_all_model_compatibility_rows(db)
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


_DOCS_LOCKED = bool(settings.openapi_admin_only)

app = FastAPI(
    title=APPLICATION_TITLE,
    version="1.0.0",
    lifespan=lifespan,
    # When docs are admin-locked, disable the public default endpoints and serve
    # them under /api/* (see below) so the session cookie (path=/api) is sent.
    docs_url=None if _DOCS_LOCKED else "/docs",
    redoc_url=None if _DOCS_LOCKED else "/redoc",
    openapi_url=None if _DOCS_LOCKED else "/openapi.json",
)


if _DOCS_LOCKED:
    from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
    from fastapi.responses import HTMLResponse, JSONResponse as _JSONResponse

    @app.get("/api/openapi.json", include_in_schema=False)
    async def _protected_openapi_json():
        return _JSONResponse(app.openapi())

    @app.get("/api/docs", include_in_schema=False)
    async def _protected_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title=f"{APPLICATION_TITLE} — API",
        )

    @app.get("/api/redoc", include_in_schema=False)
    async def _protected_redoc_html():
        return get_redoc_html(
            openapi_url="/api/openapi.json",
            title=f"{APPLICATION_TITLE} — ReDoc",
        )


app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OpenApiDocsGuardMiddleware)


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
app.include_router(user_settings.router)
app.include_router(images.router)
app.include_router(operations.router)
app.include_router(plans.router)
app.include_router(reports.router)
app.include_router(logs.router)
app.include_router(authentication.router)
app.include_router(smtp.router)
app.include_router(groups.router)
app.include_router(chat.router)


def health_payload() -> dict[str, str]:
    """Return a stable, deliberately minimal liveness response.

    Health is a public endpoint used by local operators and container probes.
    It must not enumerate routes or expose build/layout details that help
    fingerprint the application. Dependency readiness is checked separately by
    the deployment layer rather than turning this endpoint into a data probe.
    """
    return {"status": "ok", "service": PRODUCT_SLUG}


@app.get("/health", include_in_schema=False)
async def health():
    return health_payload()


def _fallback_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><title>{PRODUCT_NAME}</title></head>
<body style="font-family:system-ui;max-width:640px;margin:3rem auto;padding:1rem">
  <h1>{PRODUCT_NAME} UI not built yet</h1>
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
