"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

LDAP_BRIDGE_INSECURE_DEFAULT = "alpha-router-ldap-bridge"

# Known placeholder values that must never reach a production deployment.
# Used by the startup guard (_assert_production_safe) to refuse boot when an
# operator forgot to override the bundled dev defaults.
INSECURE_DEFAULTS: frozenset[str] = frozenset(
    {
        "change-me-in-production",  # SECRET_KEY
        "admin",  # ADMIN_PASSWORD
        "sk-alpha-router-master",  # GATEWAY_MASTER_KEY
        LDAP_BRIDGE_INSECURE_DEFAULT,
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Alpha Router"
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

    # Default admin (local auth panel)
    admin_username: str = "admin"
    admin_password: str = "admin"
    service_admin_password: str = "changeme"

    database_url: str = "postgresql+asyncpg://alpha_router:alpha_router@postgres:5432/alpha-router"  # env: DATABASE_URL
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

    # OpenAI-compatible gateway master key (Open WebUI → Alpha Router)
    gateway_master_key: str = "sk-alpha-router-master"

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
    # Windows host bridge for signed LDAP when Alpha Router runs in Docker/Linux (env: LDAP_BRIDGE_URL)
    ldap_bridge_url: str = ""
    ldap_bridge_token: str = ""

    # Keycloak OIDC
    keycloak_enabled: bool = False
    keycloak_server_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""
    keycloak_redirect_uri: str = "http://localhost:8080/auth/keycloak/callback"

    # SMTP (admin-configured)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "alpha_router@localhost"
    smtp_tls: bool = True

    # Object storage (MinIO / S3-compatible) — all media blobs
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key: str = "alpha-router"
    s3_secret_key: str = "minioadmin"
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
    # Security headers: HSTS is only emitted when enabled AND environment is
    # production (i.e. behind HTTPS). CSP is opt-in to avoid breaking the SPA
    # without testing; when empty, no CSP header is sent.
    enable_hsts: bool = False
    content_security_policy: str = ""
    # Minimum length for local-account passwords (admin create/reset). The
    # bootstrap admin password from env is not subject to this.
    password_min_length: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
