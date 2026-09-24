"""SMTP is configured in the database (Admin -> SMTP), never through SMTP_* keys.

The Settings class used to carry SMTP_HOST, SMTP_TLS and four more keys that
nothing read, and the production guard checked SMTP_TLS: an operator could
satisfy the guard with SMTP_TLS=true while mail went out in plain text
according to the saved settings. The keys are gone; an old .env that still
sets them must keep loading.
"""

import inspect

from app.config import Settings
from app.main import _check_production_safe, _collect_production_insecurities


def test_no_setting_configures_smtp():
    assert [name for name in Settings.model_fields if name.startswith("smtp_")] == []


def test_an_env_file_that_still_sets_smtp_keys_loads(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SMTP_HOST=mail.example.com\nSMTP_PORT=25\nSMTP_TLS=false\nSMTP_PASSWORD=x\n", encoding="utf-8")
    settings = Settings(_env_file=str(env))
    assert not hasattr(settings, "smtp_host")


def test_the_production_guard_does_not_check_an_smtp_key():
    for guard in (_check_production_safe, _collect_production_insecurities):
        assert [name for name in inspect.signature(guard).parameters if name.startswith("smtp")] == []
