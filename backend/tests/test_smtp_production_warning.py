"""In production, insecure saved SMTP settings are named in the log at start-up.

The settings live in the database and are chosen on purpose on the settings
page (a relay on a trusted network, a self-signed certificate), so they are a
warning, never a refused start: that would lock the administrator out of the
page that changes them.
"""

import logging

import pytest

from app.models.system import SmtpSettings
from app.services.secret_crypto import encrypt_secret
from app.services.smtp_service import insecure_setting_findings, warn_about_insecure_settings


def _row(**overrides) -> SmtpSettings:
    fields = dict(
        host="mail.example.com",
        port=587,
        username=None,
        password_encrypted=None,
        from_address="alerts@example.com",
        security="starttls",
        verify_certificate=True,
    )
    fields.update(overrides)
    return SmtpSettings(**fields)


class TestFindings:
    def test_a_verified_tls_connection_is_fine(self):
        assert insecure_setting_findings(_row()) == []
        assert insecure_setting_findings(_row(security="ssl", port=465)) == []

    def test_no_settings_or_no_host_is_nothing_to_report(self):
        assert insecure_setting_findings(None) == []
        assert insecure_setting_findings(_row(host="  ")) == []

    def test_no_tls_says_what_travels_in_plain_text(self):
        relay = insecure_setting_findings(_row(security="none", port=25))
        assert relay == ["SMTP to mail.example.com:25 uses no TLS, so messages travel in plain text"]
        with_login = insecure_setting_findings(
            _row(security="none", port=25, username="alpha", password_encrypted=encrypt_secret("s3cret"))
        )
        assert with_login == [
            "SMTP to mail.example.com:25 uses no TLS, so messages and the password travel in plain text"
        ]

    def test_an_unverified_certificate_is_reported(self):
        assert insecure_setting_findings(_row(verify_certificate=False)) == [
            "SMTP to mail.example.com:587 does not verify the server's certificate, so anyone in between can pose as it"
        ]


class TestStartupWarning:
    async def test_production_logs_each_finding(self, db_session, caplog):
        db_session.add(_row(security="none", port=25))
        await db_session.commit()
        with caplog.at_level(logging.WARNING, logger="app.services.smtp_service"):
            findings = await warn_about_insecure_settings(db_session, environment="production")
        assert len(findings) == 1
        assert "Production SMTP: SMTP to mail.example.com:25 uses no TLS" in caplog.text
        assert "Change it under Admin > SMTP." in caplog.text

    @pytest.mark.parametrize("environment", ["development", "staging", ""])
    async def test_other_environments_stay_quiet(self, db_session, caplog, environment):
        db_session.add(_row(security="none", port=25))
        await db_session.commit()
        with caplog.at_level(logging.WARNING, logger="app.services.smtp_service"):
            assert await warn_about_insecure_settings(db_session, environment=environment) == []
        assert caplog.text == ""

    async def test_secure_settings_log_nothing_in_production(self, db_session, caplog):
        db_session.add(_row())
        await db_session.commit()
        with caplog.at_level(logging.WARNING, logger="app.services.smtp_service"):
            assert await warn_about_insecure_settings(db_session, environment="production") == []
        assert caplog.text == ""


def test_start_up_runs_the_check():
    """The warning is only useful if start-up asks for it."""
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "await warn_about_insecure_settings(db, environment=settings.environment)" in main
