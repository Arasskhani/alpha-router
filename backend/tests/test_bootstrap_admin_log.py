"""Bootstrap admin credentials go to a 0600 file, never into the log."""

import logging
import os
from types import SimpleNamespace

from app.services import bootstrap_admin_log as bal
from app.services.bootstrap_admin_log import (
    BOOTSTRAP_ADMIN_LOG_MARKER,
    log_bootstrap_admin_credentials,
)


def test_credentials_are_written_to_a_private_file_and_kept_out_of_logs(caplog, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(tls_state_dir=str(tmp_path)))

    with caplog.at_level(logging.WARNING, logger="alpha_router.bootstrap_admin"):
        log_bootstrap_admin_credentials(username="alpharouter", password="secret-pass")

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert BOOTSTRAP_ADMIN_LOG_MARKER in message
    assert "username=alpharouter" in message
    assert "secret-pass" not in message
    assert "one-time" in message.lower()

    path = tmp_path / bal.BOOTSTRAP_ADMIN_FILENAME
    assert str(path) in message
    assert path.read_text() == "username=alpharouter\npassword=secret-pass\n"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_unwritable_directory_still_logs_marker_without_password(caplog, tmp_path, monkeypatch):
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("x")
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(tls_state_dir=str(blocked)))
    with caplog.at_level(logging.WARNING, logger="alpha_router.bootstrap_admin"):
        log_bootstrap_admin_credentials(username="alpharouter", password="secret-pass")
    joined = " ".join(r.message for r in caplog.records)
    assert BOOTSTRAP_ADMIN_LOG_MARKER in joined
    assert "secret-pass" not in joined
