"""Bootstrap admin one-time credential logging."""

from app.services.bootstrap_admin_log import (
    BOOTSTRAP_ADMIN_LOG_MARKER,
    log_bootstrap_admin_credentials,
)


def test_log_bootstrap_admin_credentials_emits_marker(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="alpha_router.bootstrap_admin"):
        log_bootstrap_admin_credentials(username="alpharouter", password="secret-pass")

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert BOOTSTRAP_ADMIN_LOG_MARKER in message
    assert "username=alpharouter" in message
    assert "password=secret-pass" in message
    assert "one-time" in message.lower()
