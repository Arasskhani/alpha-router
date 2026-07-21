"""Startup production guard — refuses to boot while insecure defaults are configured.

Phase 0 hardening. The guard is env-gated: a no-op unless
`settings.environment == "production"`, so existing dev/single-box deployments
(which default to "development") boot unchanged.

Phase 9 expands the guard to Redis auth, a dedicated data-encryption key, and
admin-only OpenAPI docs, and adds a `production_guard_mode` toggle between
`warning` (log + continue) and `hard-fail` (raise, the original behavior).
"""

import logging

import pytest

from app.config import INSECURE_DEFAULTS, Settings, get_settings
from app.main import (
    _check_production_safe,
    _collect_production_insecurities,
    _redis_url_has_password,
)


def _prod_kwargs(**overrides):
    base = {
        "environment": "production",
        "secret_key": "a-real-secret-not-a-placeholder",
        "admin_password": "a-real-admin-password",
        "gateway_master_key": "a-real-master-key",
        "code_sandbox_broker_url": "http://sandbox-broker:8081",
        "code_sandbox_broker_token": "a-random-sandbox-token-with-at-least-32-chars",
        "redis_url": "redis://:a-strong-redis-password@redis:6379/0",
        "redis_password": "",
        "data_encryption_key": "a-dedicated-data-encryption-key-32+chars",
        "openapi_admin_only": True,
    }
    base.update(overrides)
    return base


def test_development_environment_is_noop_with_defaults():
    # Default environment is "development" — guard must not raise even with insecure defaults.
    _check_production_safe(
        environment="development",
        secret_key="change-me-in-production",
        admin_password="admin",
        gateway_master_key="sk-alpha-router-master",
    )


def test_production_refuses_when_all_defaults_present():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(
            secret_key="change-me-in-production",
            admin_password="admin",
            gateway_master_key="sk-alpha-router-master",
        ))
    msg = str(exc.value)
    assert "SECRET_KEY" in msg
    assert "ADMIN_PASSWORD" in msg
    assert "GATEWAY_MASTER_KEY" in msg
    assert "production" in msg.lower()


def test_production_refuses_when_only_secret_key_is_default():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(secret_key="change-me-in-production"))
    assert "SECRET_KEY" in str(exc.value)
    assert "ADMIN_PASSWORD" not in str(exc.value)
    assert "GATEWAY_MASTER_KEY" not in str(exc.value)


def test_production_refuses_when_only_admin_password_is_default():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(admin_password="admin"))
    assert "ADMIN_PASSWORD" in str(exc.value)


def test_production_refuses_when_only_gateway_master_key_is_default():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(gateway_master_key="sk-alpha-router-master"))
    assert "GATEWAY_MASTER_KEY" in str(exc.value)


def test_production_accepts_when_all_secrets_overridden():
    # No raise when all three are real, non-placeholder values.
    _check_production_safe(**_prod_kwargs())


@pytest.mark.parametrize(
    "token",
    [
        "",
        "short-token",
        "alpha-router-ldap-bridge",
    ],
)
def test_production_rejects_missing_weak_or_default_ldap_bridge_token(token):
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(
            **_prod_kwargs(
                ldap_bridge_url="http://host.docker.internal:8765",
                ldap_bridge_token=token,
            )
        )
    assert "LDAP_BRIDGE_TOKEN" in str(exc.value)


def test_production_accepts_strong_ldap_bridge_token():
    _check_production_safe(
        **_prod_kwargs(
            ldap_bridge_url="http://host.docker.internal:8765",
            ldap_bridge_token="a-random-bridge-token-with-at-least-32-chars",
        )
    )


@pytest.mark.parametrize(
    ("url", "token", "expected"),
    [
        ("", "a-random-sandbox-token-with-at-least-32-chars", "CODE_SANDBOX_BROKER_URL"),
        ("http://sandbox-broker:8081", "", "CODE_SANDBOX_BROKER_TOKEN"),
        ("http://sandbox-broker:8081", "short-token", "CODE_SANDBOX_BROKER_TOKEN"),
    ],
)
def test_production_requires_authenticated_sandbox_broker(url, token, expected):
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(
            **_prod_kwargs(
                code_sandbox_broker_url=url,
                code_sandbox_broker_token=token,
            )
        )
    assert expected in str(exc.value)


def test_production_allows_disabled_ldap_bridge_without_token():
    _check_production_safe(**_prod_kwargs(ldap_bridge_url="", ldap_bridge_token=""))


def test_empty_string_is_not_treated_as_insecure_default():
    # An operator who sets a secret to empty (e.g. disables LDAP) must not trip the guard,
    # because "" is not in INSECURE_DEFAULTS. Only the known placeholder values trip it.
    _check_production_safe(**_prod_kwargs(admin_password=""))


def test_insecure_defaults_set_contents():
    # Lock the contract: these are exactly the bundled dev placeholders the guard rejects.
    assert "change-me-in-production" in INSECURE_DEFAULTS
    assert "admin" in INSECURE_DEFAULTS
    assert "sk-alpha-router-master" in INSECURE_DEFAULTS
    assert "alpha-router-ldap-bridge" in INSECURE_DEFAULTS


def test_default_environment_is_development(monkeypatch):
    # Guarantees the env-gated default preserves current behavior for existing
    # deployments. We must observe the field default alone, independent of the
    # runtime `.env`/process environment (which may be "production" in a deployed
    # container), so disable file/env sources for this assertion.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.environment == "development"


def test_production_guard_defaults_to_hard_fail(monkeypatch):
    monkeypatch.delenv("PRODUCTION_GUARD_MODE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.production_guard_mode == "hard-fail"


# --- Phase 9: expanded checks (Redis auth, data key, OpenAPI lockdown) --------


def test_redis_url_has_password_detection():
    assert _redis_url_has_password("redis://:secret@redis:6379/0")
    assert _redis_url_has_password("rediss://:secret@redis:6379/0")
    assert _redis_url_has_password("redis://redis:6379/0", redis_password="secret")
    assert not _redis_url_has_password("redis://:changeme@redis:6379/0")
    assert not _redis_url_has_password("redis://redis:6379/0", redis_password="changeme")
    assert not _redis_url_has_password("redis://redis:6379/0")
    assert not _redis_url_has_password("redis://user@redis:6379/0")
    assert not _redis_url_has_password("http://redis:6379/0")
    assert not _redis_url_has_password("")


def test_production_flags_redis_without_password():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(redis_url="redis://redis:6379/0"))
    assert "REDIS_PASSWORD" in str(exc.value)


def test_production_flags_missing_data_encryption_key():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(data_encryption_key=""))
    assert "DATA_ENCRYPTION_KEY" in str(exc.value)


def test_production_flags_default_data_encryption_key():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(data_encryption_key="change-me-in-production"))
    assert "DATA_ENCRYPTION_KEY" in str(exc.value)


def test_production_flags_open_openapi_docs():
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(openapi_admin_only=False))
    assert "OPENAPI_DOCS" in str(exc.value)


def test_production_accepts_redis_password_setting_when_url_has_none():
    # redis_password satisfies the guard even when the URL itself has no inline password.
    _check_production_safe(**_prod_kwargs(redis_url="redis://redis:6379/0", redis_password="strong-pass"))


def test_production_warning_mode_logs_and_does_not_raise(caplog):
    with caplog.at_level(logging.WARNING, logger="alpha_router.production_guard"):
        _check_production_safe(
            **_prod_kwargs(secret_key="change-me-in-production"),
            guard_mode="warning",
        )
    messages = " ".join(r.message for r in caplog.records)
    assert "SECRET_KEY" in messages
    assert "non-blocking" in messages


def test_production_warning_mode_clean_when_secure(caplog):
    with caplog.at_level(logging.WARNING, logger="alpha_router.production_guard"):
        _check_production_safe(**_prod_kwargs(), guard_mode="warning")
    assert not [r for r in caplog.records if r.name == "alpha_router.production_guard"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"service_admin_password": "changeme"}, "SERVICE_ADMIN_PASSWORD"),
        ({"database_url": "postgresql+asyncpg://alpha_router:alpha_router@postgres:5432/alpha-router"}, "DATABASE_URL"),
        ({"keycloak_enabled": True, "keycloak_server_url": "http://keycloak", "keycloak_redirect_uri": "http://app/callback"}, "KEYCLOAK_TLS"),
        ({"smtp_host": "smtp.internal", "smtp_tls": False}, "SMTP_TLS"),
        ({"s3_endpoint_url": "http://objects.example.com", "s3_use_ssl": False}, "S3_TLS"),
        ({"s3_access_key": "alpha-router", "s3_secret_key": "minioadmin"}, "S3_CREDENTIALS"),
        ({"frontend_url": "http://app", "api_public_url": "https://api"}, "FRONTEND_TLS"),
        ({"api_public_url": "http://api", "frontend_url": "https://app"}, "API_PUBLIC_TLS"),
        ({"enable_hsts": False, "frontend_url": "https://app.example"}, "HSTS"),
        ({"allow_insecure_code_subprocess": True}, "INSECURE_CODE_SUBPROCESS"),
        ({"allow_legacy_bearer_auth": True}, "LEGACY_BEARER_AUTH"),
    ],
)
def test_production_detects_insecure_runtime_fallbacks(overrides, expected):
    with pytest.raises(RuntimeError) as exc:
        _check_production_safe(**_prod_kwargs(**overrides))
    assert expected in str(exc.value)


def test_production_allows_loopback_http_and_compose_minio_without_hsts():
    """Single-box / internal Compose installs may use loopback HTTP and MinIO."""
    _check_production_safe(
        **_prod_kwargs(
            frontend_url="http://localhost:8080",
            api_public_url="http://127.0.0.1:8080",
            enable_hsts=False,
            s3_endpoint_url="http://minio:9000",
            s3_use_ssl=False,
            allow_legacy_bearer_auth=False,
        )
    )


def test_production_hard_fail_mode_raises():
    with pytest.raises(RuntimeError):
        _check_production_safe(
            **_prod_kwargs(secret_key="change-me-in-production"),
            guard_mode="hard-fail",
        )


def test_development_is_noop_even_for_new_checks():
    # New Phase 9 checks must also be no-ops in development.
    assert (
        _collect_production_insecurities(
            environment="development",
            secret_key="change-me-in-production",
            admin_password="admin",
            gateway_master_key="sk-alpha-router-master",
            redis_url="redis://redis:6379/0",
            data_encryption_key="",
            openapi_admin_only=False,
        )
        == []
    )


def test_production_reports_full_insecurity_matrix():
    # Every insecure default at once surfaces each name exactly once.
    insecure = _collect_production_insecurities(
        environment="production",
        secret_key="change-me-in-production",
        admin_password="admin",
        gateway_master_key="sk-alpha-router-master",
        ldap_bridge_url="http://bridge:8765",
        ldap_bridge_token="short",
        code_sandbox_broker_url="",
        code_sandbox_broker_token="short",
        redis_url="redis://redis:6379/0",
        data_encryption_key="",
        openapi_admin_only=False,
    )
    assert sorted(insecure) == sorted(
        [
            "SECRET_KEY",
            "ADMIN_PASSWORD",
            "GATEWAY_MASTER_KEY",
            "LDAP_BRIDGE_TOKEN",
            "CODE_SANDBOX_BROKER_URL",
            "CODE_SANDBOX_BROKER_TOKEN",
            "REDIS_PASSWORD",
            "DATA_ENCRYPTION_KEY",
            "OPENAPI_DOCS",
        ]
    )
