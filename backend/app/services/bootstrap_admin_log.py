"""One-time bootstrap administrator credential hand-off.

The password used to be written into the container log. Logs are shipped,
retained and readable by more people than the operator who ran the install,
so the secret now goes to a root-only file inside the persisted TLS/state
volume and the log carries only the marker and the path. ``scripts/lib/
stack.sh`` prints the file once after the first health check and removes it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.branding import LOGGER_NAMESPACE

# Parsed by scripts/lib/stack.sh after first successful health check.
BOOTSTRAP_ADMIN_LOG_MARKER = "BOOTSTRAP_ADMIN_CREDENTIALS_ONCE"
BOOTSTRAP_ADMIN_FILENAME = "bootstrap-admin.txt"

_LOG = logging.getLogger(f"{LOGGER_NAMESPACE}.bootstrap_admin")


def bootstrap_admin_file() -> Path:
    from app.config import get_settings

    return Path(getattr(get_settings(), "tls_state_dir", "/app/tls")) / BOOTSTRAP_ADMIN_FILENAME


def write_bootstrap_admin_credentials(*, username: str, password: str) -> Path | None:
    """Write ``username``/``password`` to a 0600 file. Returns the path, or None on failure."""
    path = bootstrap_admin_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"username={username}\npassword={password}\n")
        os.chmod(path, 0o600)
        return path
    except OSError:
        _LOG.exception("could not write bootstrap admin credentials file %s", path)
        return None


def log_bootstrap_admin_credentials(*, username: str, password: str) -> None:
    """Record where the initial admin credentials were written. Never logs the password."""
    path = write_bootstrap_admin_credentials(username=username, password=password)
    if path is not None:
        _LOG.warning(
            "%s Alpharouter bootstrap administrator created (one-time; change after login). "
            "username=%s credentials_file=%s",
            BOOTSTRAP_ADMIN_LOG_MARKER,
            username,
            path,
        )
    else:
        _LOG.warning(
            "%s Alpharouter bootstrap administrator created (one-time). username=%s "
            "The password is ADMIN_PASSWORD from .env; the credentials file could not be written.",
            BOOTSTRAP_ADMIN_LOG_MARKER,
            username,
        )
