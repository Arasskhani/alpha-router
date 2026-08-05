"""Application configuration loaded from environment variables."""

from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.branding import (
    CSRF_COOKIE_NAME,
    GATEWAY_MASTER_KEY_DEFAULT,
    PRODUCT_NAME,
    SESSION_COOKIE_NAME,
)
from app.legacy_brand_denylist import LEGACY_INSECURE_DEFAULTS

# Known placeholder values that must never reach a production deployment.
# Used by the startup guard (_assert_production_safe) to refuse boot when an
# operator forgot to override the bundled dev defaults.
INSECURE_DEFAULTS: frozenset[str] = frozenset(
    {
        "change-me-in-production",  # SECRET_KEY
        "admin",  # ADMIN_PASSWORD
        "changeme",  # SERVICE_ADMIN_PASSWORD and template credentials
        "alpha_router",  # bundled database/S3 development identity
        "rustfsadmin",  # common S3-compatible placeholder
        "change-me-seaweed-admin",  # SEAWEEDFS_ADMIN_PASSWORD example
        GATEWAY_MASTER_KEY_DEFAULT,
    }
    | LEGACY_INSECURE_DEFAULTS
)

DEFAULT_CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "frame-src 'none'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' data: blob: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' blob:; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = PRODUCT_NAME
    debug: bool = False
    # "development" (default) keeps all hardening opt-in so existing single-box
    # deployments boot unchanged. "production" enables the startup guard that
    # refuses to boot while insecure defaults are still configured.
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    # Token lifetime. Default 8h (480 min) — balances UX against stolen-token
    # exposure. Revocation is enforced via the per-user ``token_version``
    # column (bumped on logout / password reset / admin disable), so a token
    # is also revocable before its natural expiry.
    jwt_expire_minutes: int = 480
    # Browser sessions use an HttpOnly cookie. Legacy browser Bearer JWTs are
    # disabled by default so CSRF cannot be bypassed without a session cookie.
    # /v1 API-key auth is separate and unaffected.
    enable_cookie_auth: bool = True
    allow_legacy_bearer_auth: bool = False  # env: ALLOW_LEGACY_BEARER_AUTH
    enable_csrf: bool = True
    session_cookie_name: str = SESSION_COOKIE_NAME
    csrf_cookie_name: str = CSRF_COOKIE_NAME
    csrf_header_name: str = "X-CSRF-Token"

    # Default admin (local auth panel)
    admin_username: str = "admin"
    admin_password: str = "admin"
    service_admin_password: str = "changeme"

    database_url: str = "postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router"  # env: DATABASE_URL
    database_read_url: str = ""  # env: DATABASE_READ_URL — optional read replica for GET chat routes
    db_pool_size: int = 12  # env: DB_POOL_SIZE — per worker behind PgBouncer (5k concurrent profile)
    db_max_overflow: int = 20  # env: DB_MAX_OVERFLOW
    db_pool_timeout: int = 45  # env: DB_POOL_TIMEOUT
    chat_empty_session_hide_days: int = 30  # env: CHAT_EMPTY_SESSION_HIDE_DAYS
    chat_list_rate_limit_per_min: int = 200  # env: CHAT_LIST_RATE_LIMIT_PER_MIN
    chat_list_since_rate_limit_per_min: int = 600  # env: CHAT_LIST_SINCE_RATE_LIMIT_PER_MIN
    chat_search_rate_limit_per_min: int = 45  # env: CHAT_SEARCH_RATE_LIMIT_PER_MIN
    chat_message_search_rate_limit_per_min: int = 45  # env: CHAT_MESSAGE_SEARCH_RATE_LIMIT_PER_MIN
    uvicorn_workers: int = 4  # env: UVICORN_WORKERS — process count in Docker/production
    redis_url: str = "redis://redis:6379/0"  # env: REDIS_URL
    # Phase 9: Redis auth. When set, the connection URL is rebuilt with this
    # password so rate-limit and OIDC state caches authenticate to Redis.
    redis_password: str = ""  # env: REDIS_PASSWORD
    # Dedicated data-at-rest encryption key. Production rejects this bundled
    # development placeholder; no alternate key or historical salt is tried.
    data_encryption_key: str = "change-me-in-production"  # env: DATA_ENCRYPTION_KEY
    # Phase 9: lock OpenAPI docs/redoc/openapi.json to Super Admin in production.
    # The guard flags a False value in production. Development leaves docs open.
    openapi_admin_only: bool = False  # env: OPENAPI_ADMIN_ONLY
    # Production must fail closed when an insecure fallback is still active.
    # Development is unaffected because the guard is environment-gated.
    production_guard_mode: str = "hard-fail"  # env: PRODUCTION_GUARD_MODE

    # OpenAI-compatible gateway master key (Open WebUI → Alpha Router)
    gateway_master_key: str = GATEWAY_MASTER_KEY_DEFAULT

    # Code interpreter sandbox. Alpha Router sends bounded payloads to an internal broker;
    # only that broker has access to the Docker socket and fixed sandbox policy.
    code_sandbox_broker_url: str = ""
    code_sandbox_broker_token: str = ""
    # Explicit development-only escape hatch. Production always fails closed.
    allow_insecure_code_subprocess: bool = False
    # Retained only to detect and reject a legacy image-only configuration.
    code_sandbox_image: str = ""  # env: CODE_SANDBOX_IMAGE (e.g. alpha-router-sandbox:latest)
    code_sandbox_timeout_seconds: int = 20  # env: CODE_SANDBOX_TIMEOUT_SECONDS

    # Bounded I/O defaults. Callers clamp overrides to hard safety ceilings.
    max_request_body_bytes: int = 64 * 1024 * 1024
    max_attachment_bytes: int = 12 * 1024 * 1024
    max_attachments_total_bytes: int = 36 * 1024 * 1024
    max_voice_upload_bytes: int = 25 * 1024 * 1024
    max_media_input_bytes: int = 25 * 1024 * 1024
    max_web_fetch_bytes: int = 2 * 1024 * 1024
    max_image_side_px: int = 4096
    max_image_pixels: int = 4096 * 4096
    max_zip_items: int = 100
    max_zip_single_file_bytes: int = 50 * 1024 * 1024
    max_zip_aggregate_bytes: int = 256 * 1024 * 1024

    # Conservative in-flight billing holds (USD) and stale recovery.
    budget_chat_fallback_hold_usd: float = 0.05
    budget_embedding_fallback_hold_usd: float = 0.01
    budget_image_fallback_hold_usd: float = 0.25
    budget_max_hold_usd: float = 5.0
    budget_reservation_ttl_seconds: int = 7200

    # Model sync default interval (hours)
    model_sync_interval_hours: int = 6

    # LDAP
    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_base_dn: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_filter: str = "(uid={username})"
    ldap_connect_timeout_seconds: int = 4
    ldap_receive_timeout_seconds: int = 5
    ldap_login_timeout_seconds: int = 10
    # SAML 2.0 SP (env fallback when no DB row)
    saml_enabled: bool = False
    saml_idp_metadata_url: str = ""
    saml_entity_id: str = ""
    # OIDC (env fallback when no DB row)
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    # SMTP (admin-configured)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "alpha-router@localhost"
    smtp_tls: bool = True

    # Object storage (SeaweedFS / S3-compatible) — all media blobs
    s3_endpoint_url: str = "http://127.0.0.1:8333"
    s3_access_key: str = "alpha_router"
    s3_secret_key: str = "changeme"
    s3_bucket: str = "alpha-router-media"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False
    media_cdn_prefix: str = "cdn"

    # CORS / frontend
    frontend_url: str = "http://127.0.0.1:8080"
    api_public_url: str = "http://localhost:8000"
    # Headless PDF: chrome | msedge | chromium (bundled; requires playwright install chromium)
    playwright_browser_channel: str = "chrome"

    # SSRF protection: block user-supplied fetches that resolve to private /
    # loopback / link-local / metadata IPs. Set to true ONLY for self-hosted
    # internal deployments where users must fetch from private servers.
    allow_ssrf_private_ranges: bool = False
    # Rollback switch for connection-time DNS pinning only. Base SSRF validation
    # remains active even when this is disabled.
    enable_ssrf_dns_pinning: bool = True
    # Browser hardening: CSP begins in Report-Only mode. Enforced CSP is opt-in.
    # HSTS additionally requires production and an HTTPS request/proxy signal.
    enable_hsts: bool = False
    hsts_max_age_seconds: int = 300
    hsts_include_subdomains: bool = False
    content_security_policy_report_only: str = DEFAULT_CSP_REPORT_ONLY
    content_security_policy: str = ""
    # Minimum length for local-account passwords (admin create/reset). The
    # bootstrap admin password from env is not subject to this.
    password_min_length: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()


def build_redis_url(redis_url: str, redis_password: str) -> str:
    """Return ``redis_url`` with ``redis_password`` embedded when not already present.

    Phase 9: Redis auth. Operators set ``REDIS_PASSWORD`` and every Redis client
    (rate-limit, OIDC exchange, LiteLLM cache) authenticates without having to
    embed credentials in ``REDIS_URL``. A URL that already carries a password is
    returned unchanged so explicit URLs keep working.
    """
    url = (redis_url or "").strip()
    password = (redis_password or "").strip()
    if not url:
        return url
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if parsed.scheme not in {"redis", "rediss"}:
        return url
    if parsed.password:
        return url
    if not password:
        return url
    username = parsed.username or ""
    userinfo = f"{username}:{password}@" if username else f":{password}@"
    host = parsed.hostname or ""
    netloc = f"{userinfo}{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def effective_redis_url() -> str:
    """Resolve the Redis URL with the optional ``REDIS_PASSWORD`` applied."""
    settings = get_settings()
    return build_redis_url(settings.redis_url, settings.redis_password)
