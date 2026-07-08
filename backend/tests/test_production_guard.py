"""Startup production guard — refuses to boot while insecure defaults are configured.

Phase 0 hardening. The guard is env-gated: a no-op unless
`settings.environment == "production"`, so existing dev/single-box deployments
(which default to "development") boot unchanged.
"""

import pytest

from app.config import INSECURE_DEFAULTS, get_settings
from app.main import _check_production_safe


def _prod_kwargs(**overrides):
    base = {
        "environment": "production",
        "secret_key": "a-real-secret-not-a-placeholder",
        "admin_password": "a-real-admin-password",
        "gateway_master_key": "a-real-master-key",
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


def test_empty_string_is_not_treated_as_insecure_default():
    # An operator who sets a secret to empty (e.g. disables LDAP) must not trip the guard,
    # because "" is not in INSECURE_DEFAULTS. Only the known placeholder values trip it.
    _check_production_safe(**_prod_kwargs(admin_password=""))


def test_insecure_defaults_set_contents():
    # Lock the contract: these are exactly the bundled dev placeholders the guard rejects.
    assert "change-me-in-production" in INSECURE_DEFAULTS
    assert "admin" in INSECURE_DEFAULTS
    assert "sk-alpha-router-master" in INSECURE_DEFAULTS


def test_default_environment_is_development():
    # Guarantees the env-gated default preserves current behavior for existing deployments.
    assert get_settings().environment == "development"
