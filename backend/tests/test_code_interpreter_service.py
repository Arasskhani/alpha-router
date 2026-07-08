"""Tests for sandboxed code interpreter helpers."""

import asyncio
import json
import shutil

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


# ---- container routing (no real docker needed) ----

def _clear_settings_cache():
    get_settings.cache_clear()


def test_run_sandbox_uses_subprocess_when_no_image(monkeypatch):
    """With no CODE_SANDBOX_IMAGE, execution must take the legacy subprocess path."""
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    _clear_settings_cache()

    calls = {"subprocess": 0, "container": 0}

    async def fake_sub(code, files):
        calls["subprocess"] += 1
        return "sub-ok"

    async def fake_cont(code, files, settings, image):
        calls["container"] += 1
        return "cont-ok"

    monkeypatch.setattr(cis, "_run_in_subprocess", fake_sub)
    monkeypatch.setattr(cis, "_run_in_container", fake_cont)

    out = asyncio.run(run_python_sandbox("print(1)"))
    assert out == "sub-ok"
    assert calls == {"subprocess": 1, "container": 0}
    _clear_settings_cache()


def test_run_sandbox_uses_container_when_image_set(monkeypatch):
    """With CODE_SANDBOX_IMAGE set, execution must take the container path."""
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "nitro-sandbox:latest")
    _clear_settings_cache()

    captured = {}

    async def fake_cont(code, files, settings, image):
        captured["image"] = image
        captured["code"] = code
        return "cont-ok"

    monkeypatch.setattr(cis, "_run_in_container", fake_cont)

    out = asyncio.run(run_python_sandbox("print(2)", {"a.txt": "hi"}))
    assert out == "cont-ok"
    assert captured["image"] == "nitro-sandbox:latest"
    assert "print(2)" in captured["code"]
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    _clear_settings_cache()


def test_run_sandbox_container_still_blocks_disallowed_imports(monkeypatch):
    """AST validation runs before any container spawn (defense in depth)."""
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "nitro-sandbox:latest")
    _clear_settings_cache()

    async def fake_cont(code, files, settings, image):
        raise AssertionError("must not spawn container for blocked import")

    monkeypatch.setattr(cis, "_run_in_container", fake_cont)
    with pytest.raises(ValueError, match="Import not allowed"):
        asyncio.run(run_python_sandbox("import os"))
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    _clear_settings_cache()


# ---- real docker integration (skipped unless image is available) ----

def _sandbox_image_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = asyncio.run(_docker_image_exists("nitro-sandbox:latest"))
    except Exception:
        return False
    return r


async def _docker_image_exists(image: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", image,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return proc.returncode == 0


_DOCKER = pytest.mark.skipif(
    not _sandbox_image_available(),
    reason="nitro-sandbox:latest not available or docker missing",
)


@_DOCKER
def test_container_runs_basic_code(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "nitro-sandbox:latest")
    _clear_settings_cache()
    out = asyncio.run(run_python_sandbox("print(6*7)"))
    assert "42" in out
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    _clear_settings_cache()


@_DOCKER
def test_container_has_no_network(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "nitro-sandbox:latest")
    _clear_settings_cache()
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('NET_OK')\n"
        "except Exception as e:\n"
        "    print('NET_BLOCKED')\n"
    )
    # socket import is blocklisted by AST, so call via builtins to reach runtime.
    code = code.replace("import socket", "socket = __import__('socket')")
    out = asyncio.run(run_python_sandbox(code))
    assert "NET_BLOCKED" in out
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    _clear_settings_cache()


@_DOCKER
def test_container_has_no_app_secrets(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "nitro-sandbox:latest")
    _clear_settings_cache()
    code = (
        "os = __import__('os')\n"
        "leaked = [k for k in os.environ if k in ('SECRET_KEY','DATABASE_URL','GATEWAY_MASTER_KEY','S3_SECRET_KEY')]\n"
        "print('LEAK' if leaked else 'CLEAN')\n"
    )
    out = asyncio.run(run_python_sandbox(code))
    assert "CLEAN" in out
    monkeypatch.delenv("CODE_SANDBOX_IMAGE", raising=False)
    _clear_settings_cache()
