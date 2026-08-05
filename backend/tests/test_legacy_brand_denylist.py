"""Security checks for intentionally retained stale-configuration literals."""

import pytest

from app.legacy_brand_denylist import (
    LEGACY_CSRF_COOKIE_NAMES,
    LEGACY_DATABASE_URLS,
    LEGACY_GATEWAY_MASTER_KEYS,
    LEGACY_INFRASTRUCTURE_IDENTITIES,
    LEGACY_SESSION_COOKIE_NAMES,
)
from app.main import _check_production_safe


def _production_config(**overrides):
    config = {
        "environment": "production",
        "secret_key": "production-secret-value",
        "admin_password": "production-admin-password",
        "gateway_master_key": "production-master-key",
        "code_sandbox_broker_url": "http://sandbox-broker:8081",
        "code_sandbox_broker_token": "production-sandbox-token-with-32-characters",
        "redis_url": "redis://:production-password@redis:6379/0",
        "redis_password": "",
        "data_encryption_key": "production-data-encryption-key",
        "openapi_admin_only": True,
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize("cookie_name", LEGACY_SESSION_COOKIE_NAMES)
def test_stale_session_cookie_config_is_rejected(cookie_name):
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_NAME"):
        _check_production_safe(
            **_production_config(session_cookie_name=cookie_name)
        )


@pytest.mark.parametrize("cookie_name", LEGACY_CSRF_COOKIE_NAMES)
def test_stale_csrf_cookie_config_is_rejected(cookie_name):
    with pytest.raises(RuntimeError, match="CSRF_COOKIE_NAME"):
        _check_production_safe(**_production_config(csrf_cookie_name=cookie_name))


@pytest.mark.parametrize("master_key", LEGACY_GATEWAY_MASTER_KEYS)
def test_stale_master_key_config_is_rejected(master_key):
    with pytest.raises(RuntimeError, match="GATEWAY_MASTER_KEY"):
        _check_production_safe(**_production_config(gateway_master_key=master_key))


@pytest.mark.parametrize("database_url", LEGACY_DATABASE_URLS)
def test_stale_database_config_is_rejected(database_url):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        _check_production_safe(**_production_config(database_url=database_url))


@pytest.mark.parametrize("identity", LEGACY_INFRASTRUCTURE_IDENTITIES)
def test_stale_object_storage_identity_is_rejected(identity):
    with pytest.raises(RuntimeError, match="S3_CREDENTIALS"):
        _check_production_safe(
            **_production_config(
                s3_access_key=identity,
                s3_secret_key="production-secret",
            )
        )
