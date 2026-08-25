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
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

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
    admin_username: str = "alpharouter"
    admin_password: str = "admin"
    service_admin_password: str = "changeme"

    database_url: str = "postgresql+asyncpg://alpha_router:changeme@postgres:5432/alpha_router"  # env: DATABASE_URL
    database_read_url: str = (
        ""  # env: DATABASE_READ_URL — optional read replica for GET chat routes
    )
    db_pool_size: int = (
        12  # env: DB_POOL_SIZE — per worker behind PgBouncer (5k concurrent profile)
    )
    db_max_overflow: int = 20  # env: DB_MAX_OVERFLOW
    db_pool_timeout: int = 45  # env: DB_POOL_TIMEOUT
    chat_empty_session_hide_days: int = 30  # env: CHAT_EMPTY_SESSION_HIDE_DAYS
    chat_list_rate_limit_per_min: int = 200  # env: CHAT_LIST_RATE_LIMIT_PER_MIN
    chat_list_since_rate_limit_per_min: int = (
        600  # env: CHAT_LIST_SINCE_RATE_LIMIT_PER_MIN
    )
    chat_search_rate_limit_per_min: int = 45  # env: CHAT_SEARCH_RATE_LIMIT_PER_MIN
    chat_message_search_rate_limit_per_min: int = (
        45  # env: CHAT_MESSAGE_SEARCH_RATE_LIMIT_PER_MIN
    )
    uvicorn_workers: int = (
        4  # env: UVICORN_WORKERS — process count in Docker/production
    )
    redis_url: str = "redis://redis:6379/0"  # env: REDIS_URL
    # Phase 9: Redis auth. When set, the connection URL is rebuilt with this
    # password so rate-limit and OIDC state caches authenticate to Redis.
    redis_password: str = ""  # env: REDIS_PASSWORD
    # Agent Knowledge data plane. Qdrant stores derived vectors only; PostgreSQL
    # remains authoritative for content, releases, ACLs, and job state.
    qdrant_url: str = "http://qdrant:6333"  # env: QDRANT_URL
    qdrant_api_key: str = ""  # env: QDRANT_API_KEY
    qdrant_timeout_seconds: float = 10.0
    qdrant_collection_prefix: str = "alpharouter-knowledge"
    qdrant_memory_collection_prefix: str = "alpharouter-memory"
    qdrant_replication_factor: int = 1
    knowledge_stream_name: str = "alpharouter:knowledge:jobs"
    knowledge_dead_letter_stream_name: str = "alpharouter:knowledge:dead"
    knowledge_consumer_group: str = "alpharouter-knowledge-workers"
    knowledge_worker_block_ms: int = 5000
    knowledge_worker_batch_size: int = 10
    knowledge_job_lease_seconds: int = 120
    knowledge_job_max_attempts: int = 5
    knowledge_retry_base_seconds: int = 5
    outbox_batch_size: int = 100
    outbox_lease_seconds: int = 60
    outbox_poll_interval_seconds: float = 0.5
    knowledge_reaper_interval_seconds: int = 30
    knowledge_connector_poll_interval_seconds: int = 60
    knowledge_retention_poll_interval_seconds: int = 3600
    knowledge_retention_batch_size: int = 100
    knowledge_max_upload_bytes: int = 50 * 1024 * 1024
    knowledge_max_archive_entries: int = 10_000
    knowledge_max_archive_uncompressed_bytes: int = 250 * 1024 * 1024
    knowledge_max_archive_ratio: int = 100
    knowledge_max_document_characters: int = 20_000_000
    knowledge_max_pdf_pages: int = 5_000
    knowledge_quarantine_prefix: str = "private/knowledge/quarantine"
    knowledge_object_prefix: str = "private/knowledge/documents"
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_scan_timeout_seconds: int = 120
    clamav_required: bool = True
    knowledge_ocr_required: bool = True
    knowledge_ocr_languages: str = "fas+eng"
    knowledge_ocr_dpi: int = 200
    knowledge_ocr_page_timeout_seconds: int = 45
    knowledge_ocr_max_pages: int = 500
    knowledge_ocr_min_text_characters: int = 40
    knowledge_parser_timeout_seconds: int = 300
    # Scanned PDF OCR (MuPDF render + Tesseract) routinely needs >1 GiB RSS.
    knowledge_parser_memory_bytes: int = 1536 * 1024 * 1024
    knowledge_parser_cpu_seconds: int = 240
    knowledge_parser_max_output_bytes: int = 96 * 1024 * 1024
    knowledge_embedding_batch_size: int = 32
    knowledge_embedding_max_input_characters: int = 16_000
    knowledge_embedding_timeout_seconds: float = 60.0
    # Automatic long-term memory. Extraction is a no-op until an admin selects a model.
    memory_extract_enabled: bool = True
    memory_job_lease_seconds: int = 120
    memory_job_max_attempts: int = 5
    memory_retry_base_seconds: int = 5
    knowledge_index_upsert_batch_size: int = 128
    knowledge_retrieval_max_query_characters: int = 8_000
    knowledge_retrieval_candidate_limit: int = 40
    knowledge_retrieval_final_limit: int = 8
    knowledge_retrieval_rrf_k: int = 60
    knowledge_retrieval_max_chunks_per_document: int = 3
    knowledge_retrieval_context_token_budget: int = 6_000
    knowledge_retrieval_dense_score_threshold: float = 0.05
    knowledge_retrieval_sparse_score_threshold: float = 0.01
    # Bounded specialist Agent runtime. Per-version policies may lower these
    # values, but cannot exceed the hard ceilings enforced by the services.
    agent_router_max_candidates: int = 64
    agent_router_minimum_confidence: float = 0.30
    agent_router_minimum_margin: float = 0.10
    agent_max_handoffs_per_turn: int = 2
    agent_max_tool_calls_per_turn: int = 8
    agent_max_tool_hops_per_turn: int = 3
    agent_tool_default_timeout_seconds: int = 20
    agent_tool_max_output_bytes: int = 256 * 1024
    agent_guardrail_timeout_seconds: int = 5
    agent_turn_timeout_seconds: int = 180
    agent_max_system_prompt_characters: int = 100_000
    # Fleet observability. Metrics use fixed labels only; tracing is opt-in
    # because production must provide an authenticated internal OTLP endpoint.
    metrics_enabled: bool = True
    metrics_bearer_token: str = ""
    json_logging_enabled: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "alpharouter"
    otel_exporter_otlp_endpoint: str = ""
    otel_trace_sample_ratio: float = 0.10
    # Dedicated data-at-rest encryption key. Production rejects this bundled
    # development placeholder; no alternate key or historical salt is tried.
    data_encryption_key: str = "change-me-in-production"  # env: DATA_ENCRYPTION_KEY
    # Phase 9: lock OpenAPI docs/redoc/openapi.json to Super Admin in production.
    # The guard flags a False value in production. Development leaves docs open.
    openapi_admin_only: bool = False  # env: OPENAPI_ADMIN_ONLY
    # Production must fail closed when an insecure fallback is still active.
    # Development is unaffected because the guard is environment-gated.
    production_guard_mode: str = "hard-fail"  # env: PRODUCTION_GUARD_MODE

    # OpenAI-compatible gateway master key (Open WebUI → Alpharouter)
    gateway_master_key: str = GATEWAY_MASTER_KEY_DEFAULT

    # Code interpreter sandbox. Alpharouter sends bounded payloads to an internal broker;
    # only that broker has access to the Docker socket and fixed sandbox policy.
    code_sandbox_broker_url: str = ""
    code_sandbox_broker_token: str = ""
    # Explicit development-only escape hatch. Production always fails closed.
    allow_insecure_code_subprocess: bool = False
    # Retained only to detect and reject a legacy image-only configuration.
    code_sandbox_image: str = (
        ""  # env: CODE_SANDBOX_IMAGE (e.g. alpha-router-sandbox:latest)
    )
    code_sandbox_timeout_seconds: int = 20  # env: CODE_SANDBOX_TIMEOUT_SECONDS
    # Cross-worker Code Interpreter turn admission (Redis leased semaphore).
    # Global hard ceiling for concurrent CI turns; request over capacity is
    # rejected immediately (no queue) with HTTP 429 + Retry-After.
    code_interpreter_capacity_global_max: int = (
        200  # env: CODE_INTERPRETER_CAPACITY_GLOBAL_MAX
    )
    code_interpreter_capacity_per_subject_max: int = (
        2  # env: CODE_INTERPRETER_CAPACITY_PER_SUBJECT_MAX
    )
    code_interpreter_capacity_lease_ttl_seconds: int = (
        900  # env: CODE_INTERPRETER_CAPACITY_LEASE_TTL_SECONDS
    )
    code_interpreter_capacity_heartbeat_seconds: int = (
        30  # env: CODE_INTERPRETER_CAPACITY_HEARTBEAT_SECONDS
    )
    code_interpreter_capacity_retry_after_seconds: int = (
        30  # env: CODE_INTERPRETER_CAPACITY_RETRY_AFTER_SECONDS
    )

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
    budget_video_fallback_hold_usd: float = 1.50
    budget_audio_fallback_hold_usd: float = 0.10
    budget_tool_fallback_hold_usd: float = 0.05
    budget_max_hold_usd: float = 5.0
    budget_reservation_ttl_seconds: int = 7200

    # Video generation (OpenRouter /videos async jobs)
    video_max_duration_seconds: int = 8
    video_max_resolution: str = "1080p"
    video_max_output_bytes: int = 200 * 1024 * 1024
    video_max_concurrent_jobs_per_user: int = 1
    video_job_poll_interval_ms: int = 2500
    video_job_timeout_seconds: int = 600
    video_job_reclaim_after_seconds: int = 900
    cost_reconciliation_enabled: bool = True
    cost_reconciliation_interval_minutes: int = 30
    cost_reconciliation_batch_size: int = 50

    # Text-to-Speech generation (sync, like images)
    audio_max_output_bytes: int = 50 * 1024 * 1024
    speech_max_text_length: int = 5000
    speech_request_timeout_seconds: int = 120

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
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def effective_redis_url() -> str:
    """Resolve the Redis URL with the optional ``REDIS_PASSWORD`` applied."""
    settings = get_settings()
    return build_redis_url(settings.redis_url, settings.redis_password)
