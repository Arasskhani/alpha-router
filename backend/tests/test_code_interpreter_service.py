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
    """Without a broker URL, execution takes the temporary compatibility path."""
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
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


def test_run_sandbox_uses_broker_when_configured(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
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


def test_run_sandbox_broker_still_blocks_disallowed_imports(monkeypatch):
    """AST validation runs before a broker request (defense in depth)."""
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
    _clear_settings_cache()

    async def fake_broker(code, files, settings, broker_url):
        raise AssertionError("must not call broker for blocked import")

    monkeypatch.setattr(cis, "_run_via_broker", fake_broker)
    with pytest.raises(ValueError, match="Import not allowed"):
        asyncio.run(run_python_sandbox("import os"))
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    _clear_settings_cache()
