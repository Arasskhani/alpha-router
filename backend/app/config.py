"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known placeholder values that must never reach a production deployment.
# Used by the startup guard (_assert_production_safe) to refuse boot when an
# operator forgot to override the bundled dev defaults.
INSECURE_DEFAULTS: frozenset[str] = frozenset(
    {
        "change-me-in-production",  # SECRET_KEY
        "admin",  # ADMIN_PASSWORD
        "sk-nitro-master",  # GATEWAY_MASTER_KEY
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NITRO"
    debug: bool = False
    # "development" (default) keeps all hardening opt-in so existing single-box
    # deployments boot unchanged. "production" enables the startup guard that
    # refuses to boot while insecure defaults are still configured.
    environment: str = "development"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Default admin (local auth panel)
    admin_username: str = "admin"
    admin_password: str = "admin"
    service_admin_password: str = "changeme"

    database_url: str = "postgresql+asyncpg://nitro:nitro@postgres:5432/nitro"  # env: DATABASE_URL
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

    # OpenAI-compatible gateway master key (Open WebUI → NITRO)
    gateway_master_key: str = "sk-nitro-master"

    # Code interpreter sandbox (Phase 2). When code_sandbox_image is set, user code
    # runs in a disposable, network-less, read-only container instead of an in-process
    # subprocess. Empty string disables container isolation (legacy subprocess path).
    code_sandbox_image: str = ""  # env: CODE_SANDBOX_IMAGE (e.g. nitro-sandbox:latest)
    code_sandbox_timeout_seconds: int = 20  # env: CODE_SANDBOX_TIMEOUT_SECONDS
    code_sandbox_memory: str = "256m"  # env: CODE_SANDBOX_MEMORY
    code_sandbox_pids_limit: int = 128  # env: CODE_SANDBOX_PIDS_LIMIT

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
    # Windows host bridge for signed LDAP when NITRO runs in Docker/Linux (env: LDAP_BRIDGE_URL)
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
    smtp_from: str = "nitro@localhost"
    smtp_tls: bool = True

    # Object storage (MinIO / S3-compatible) — all media blobs
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key: str = "nitro"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "nitro-media"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False
    media_cdn_prefix: str = "cdn"

    # CORS / frontend
    frontend_url: str = "http://127.0.0.1:8080"
    api_public_url: str = "http://localhost:8000"
    # Headless PDF: chrome | msedge | chromium (bundled; requires playwright install chromium)
    playwright_browser_channel: str = "chrome"


@lru_cache
def get_settings() -> Settings:
    return Settings()
