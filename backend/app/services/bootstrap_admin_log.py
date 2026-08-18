"""One-time bootstrap administrator credential logging."""

from __future__ import annotations

import logging

from app.branding import LOGGER_NAMESPACE

# Parsed by scripts/install.sh after first successful health check.
BOOTSTRAP_ADMIN_LOG_MARKER = "BOOTSTRAP_ADMIN_CREDENTIALS_ONCE"

_LOG = logging.getLogger(f"{LOGGER_NAMESPACE}.bootstrap_admin")


def log_bootstrap_admin_credentials(*, username: str, password: str) -> None:
    """Log the initial admin password exactly once when the bootstrap user is created."""
    _LOG.warning(
        "%s Alpharouter bootstrap administrator created (one-time; change after login). "
        "username=%s password=%s",
        BOOTSTRAP_ADMIN_LOG_MARKER,
        username,
        password,
    )
