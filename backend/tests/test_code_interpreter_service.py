"""Tests for sandboxed code interpreter helpers."""

import asyncio
import json

import pytest

import app.services.code_interpreter_service as cis
from app.config import get_settings
from app.services.code_interpreter_service import (
    code_interpreter_system_message,
    extract_last_python_block,
    format_code_output_for_chat,
    run_python_sandbox,
    validate_python_code,
    workspace_files_from_messages,
)


def test_extract_last_python_block():
    text = "Try this:\n```python\nprint(1)\n```\nand\n```py\nprint(2)\n```"
    assert extract_last_python_block(text) == "print(2)"


def test_validate_python_code_blocks_os_import():
    with pytest.raises(ValueError, match="Import not allowed"):
        validate_python_code("import os\nprint(os.getcwd())")


def test_workspace_files_from_attachment_sections():
    messages = [
        {
            "role": "user",
            "content": "Analyze\n\n--- sales.csv ---\nname,value\na,1\nb,2",
        }
    ]
    files = workspace_files_from_messages(messages)
    assert files["sales.csv"].startswith("name,value")


def test_code_interpreter_system_english_comments_and_ltr():
    msg = code_interpreter_system_message()
    assert "English-only comments" in msg
    assert "Persian/Farsi comments" in msg
    assert "Keep all code LTR" in msg


def test_format_code_output_uses_text_fence():
    out = format_code_output_for_chat("hello\nworld")
    assert "```text\nhello\nworld\n```" in out


def test_workspace_files_from_attach_json():
    payload = (
        '__NITRO_ATTACH_JSON__:{"userText":"go","attachments":[{"name":"data.csv","kind":"document",'
        '"mime_type":"text/csv","url":"","text":"x,y\\n1,2"}]}'
    )
    files = workspace_files_from_messages([{"role": "user", "content": payload}])
    assert "data.csv" in files


# ---- broker routing (no real Docker needed) ----

def _clear_settings_cache():
    get_settings.cache_clear()


def test_run_sandbox_uses_subprocess_when_no_broker(monkeypatch):
    """A subprocess requires an explicit development-only opt-in."""
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_INSECURE_CODE_SUBPROCESS", "true")
    _clear_settings_cache()

    calls = {"subprocess": 0, "broker": 0}

    async def fake_sub(code, files):
        calls["subprocess"] += 1
        return "sub-ok"

    async def fake_broker(code, files, settings, broker_url):
        calls["broker"] += 1
        return "broker-ok"

    monkeypatch.setattr(cis, "_run_in_subprocess", fake_sub)
    monkeypatch.setattr(cis, "_run_via_broker", fake_broker)

    out = asyncio.run(run_python_sandbox("print(1)"))
    assert out == "sub-ok"
    assert calls == {"subprocess": 1, "broker": 0}
    _clear_settings_cache()


@pytest.mark.parametrize(
    ("environment", "allow_subprocess"),
    [
        ("production", "true"),
        ("production", "false"),
        ("development", "false"),
    ],
)
def test_run_sandbox_fails_closed_without_broker(
    monkeypatch,
    environment: str,
    allow_subprocess: str,
):
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("ALLOW_INSECURE_CODE_SUBPROCESS", allow_subprocess)
    _clear_settings_cache()

    async def forbidden_subprocess(code, files):
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(cis, "_run_in_subprocess", forbidden_subprocess)
    out = asyncio.run(run_python_sandbox("print(1)"))
    assert "sandbox broker is required" in out
    _clear_settings_cache()


def test_legacy_image_only_configuration_cannot_downgrade(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "nitro-sandbox:latest")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_INSECURE_CODE_SUBPROCESS", "true")
    _clear_settings_cache()

    async def forbidden_subprocess(code, files):
        raise AssertionError("legacy image config must not downgrade")

    monkeypatch.setattr(cis, "_run_in_subprocess", forbidden_subprocess)
    out = asyncio.run(run_python_sandbox("print(1)"))
    assert "legacy sandbox image configuration" in out
    _clear_settings_cache()


def test_run_sandbox_uses_broker_when_configured(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
    monkeypatch.setenv("CODE_SANDBOX_BROKER_TOKEN", "t" * 48)
    _clear_settings_cache()

    captured = {}

    async def fake_broker(code, files, settings, broker_url):
        captured["broker_url"] = broker_url
        captured["code"] = code
        return "broker-ok"

    monkeypatch.setattr(cis, "_run_via_broker", fake_broker)

    out = asyncio.run(run_python_sandbox("print(2)", {"a.txt": "hi"}))
    assert out == "broker-ok"
    assert captured["broker_url"] == "http://sandbox-broker:8081"
    assert "print(2)" in captured["code"]
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    _clear_settings_cache()


def test_run_sandbox_rejects_broker_without_strong_token(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
    monkeypatch.setenv("CODE_SANDBOX_BROKER_TOKEN", "short")
    _clear_settings_cache()

    async def forbidden_broker(code, files, settings, broker_url):
        raise AssertionError("unauthenticated broker request must not be sent")

    monkeypatch.setattr(cis, "_run_via_broker", forbidden_broker)
    out = asyncio.run(run_python_sandbox("print(1)"))
    assert "broker authentication is not configured" in out
    _clear_settings_cache()


def test_run_sandbox_broker_still_blocks_disallowed_imports(monkeypatch):
    """AST validation runs before a broker request (defense in depth)."""
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
    monkeypatch.setenv("CODE_SANDBOX_BROKER_TOKEN", "t" * 48)
    _clear_settings_cache()

    async def fake_broker(code, files, settings, broker_url):
        raise AssertionError("must not call broker for blocked import")

    monkeypatch.setattr(cis, "_run_via_broker", fake_broker)
    with pytest.raises(ValueError, match="Import not allowed"):
        asyncio.run(run_python_sandbox("import os"))
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    _clear_settings_cache()


def test_dynamic_import_is_blocked_before_execution():
    _clear_settings_cache()
    with pytest.raises(ValueError, match="Dynamic import"):
        validate_python_code("socket = __import__('socket')")


def test_development_subprocess_receives_scrubbed_environment(monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"ok\n", b""

    async def fake_spawn(*args, **kwargs):
        del args
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(cis.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setenv("SECRET_KEY", "must-not-propagate")
    out = asyncio.run(cis._run_in_subprocess("print('ok')", {}))
    assert "ok" in out
    assert "SECRET_KEY" not in captured["env"]
    assert set(captured["env"]) == {"PATH", "PYTHONIOENCODING", "PYTHONUNBUFFERED"}
