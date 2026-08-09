"""Tests for sandboxed code interpreter helpers."""

import asyncio
import base64
import hashlib
import json
import re

import pytest

import app.services.code_interpreter_service as cis
from app.config import get_settings
from app.sandbox.filenames import is_safe_filename
from app.services.code_interpreter_service import (
    WorkspaceLimitError,
    build_workspace_manifest,
    code_interpreter_error_hint,
    code_interpreter_nudge_message,
    code_interpreter_system_message,
    code_interpreter_workspace_message,
    extract_last_python_block,
    format_code_output_for_chat,
    run_python_sandbox,
    SandboxExecutionResult,
    sanitize_workspace_filename,
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


def test_workspace_manifest_accepts_one_hundred_small_files():
    attachments = [
        {
            "name": f"note-{index}.txt",
            "kind": "document",
            "mime_type": "text/plain",
            "url": "",
            "text": f"row {index}",
        }
        for index in range(100)
    ]
    payload = f'__ALPHA_ROUTER_ATTACH_JSON__:{json.dumps({"userText": "analyze", "attachments": attachments})}'

    manifest = build_workspace_manifest(
        [{"role": "user", "content": payload}],
        max_files=100,
        max_total_bytes=1024 * 1024,
    )

    assert len(manifest.files) == 100
    assert manifest.total_bytes == sum(item.size_bytes for item in manifest.files)
    assert all(item.sha256 for item in manifest.files)


def test_workspace_manifest_rejects_file_count_without_silent_drop():
    attachments = [
        {
            "name": f"note-{index}.txt",
            "kind": "document",
            "mime_type": "text/plain",
            "url": "",
            "text": "x",
        }
        for index in range(101)
    ]
    payload = f'__ALPHA_ROUTER_ATTACH_JSON__:{json.dumps({"userText": "analyze", "attachments": attachments})}'

    with pytest.raises(WorkspaceLimitError) as exc:
        build_workspace_manifest(
            [{"role": "user", "content": payload}],
            max_files=100,
            max_total_bytes=1024 * 1024,
        )

    assert exc.value.file_count == 101
    assert exc.value.api_detail()["code"] == "code_interpreter_workspace_limit"


def test_workspace_manifest_rejects_total_bytes_without_truncation():
    payload = (
        '__ALPHA_ROUTER_ATTACH_JSON__:{"userText":"go","attachments":['
        '{"name":"a.txt","kind":"document","mime_type":"text/plain","url":"","text":"12345"},'
        '{"name":"b.txt","kind":"document","mime_type":"text/plain","url":"","text":"67890"}]}'
    )

    with pytest.raises(WorkspaceLimitError, match="configured total limit"):
        build_workspace_manifest(
            [{"role": "user", "content": payload}],
            max_files=10,
            max_total_bytes=9,
        )


def test_workspace_inventory_lists_every_configured_file():
    files = {f"note_{index}.txt": "x" for index in range(100)}

    inventory = code_interpreter_workspace_message(files)

    assert "There are 100 files" in inventory
    assert "note_0.txt" in inventory
    assert "note_99.txt" in inventory


def test_code_interpreter_system_english_comments_and_ltr():
    msg = code_interpreter_system_message()
    assert "English-only comments" in msg
    assert "Persian/Farsi comments" in msg
    assert "Keep all code LTR" in msg
    assert "pd.read_csv" in msg
    assert "Without a ```python block, no code runs" in msg
    assert "ReportLab" in msg
    assert "Never invent sandbox:" in msg
    assert "os, sys, pathlib" in msg
    assert "Import not allowed" in msg
    assert "'DejaVuSans' is ALREADY registered" in msg
    assert "matplotlib is NOT installed" in msg


def test_code_interpreter_error_hint_for_blocked_import():
    hint = code_interpreter_error_hint("Code interpreter error: Import not allowed: os")
    assert "blocked import" in hint
    assert "DejaVuSans" in hint
    assert "never import os" in hint.lower()


def test_code_interpreter_error_hint_for_matplotlib():
    hint = code_interpreter_error_hint("ModuleNotFoundError: No module named 'matplotlib'")
    assert "matplotlib is not installed" in hint
    assert "ReportLab" in hint


def test_code_interpreter_error_hint_empty_for_unrelated_errors():
    assert code_interpreter_error_hint("ZeroDivisionError: division by zero") == ""
    assert code_interpreter_error_hint("") == ""


def test_code_interpreter_nudge_lists_workspace_files():
    msg = code_interpreter_nudge_message({"sales.csv": "a,b\n1,2"})
    assert "```python" in msg
    assert "sales.csv" in msg
    assert "exact filenames" in msg
    assert "pd.read_csv" in msg


def test_format_code_output_uses_text_fence():
    out = format_code_output_for_chat(
        SandboxExecutionResult(output="hello\nworld", exit_code=0)
    )
    assert "```text\nhello\nworld\n```" in out


def test_workspace_files_from_attach_json():
    payload = (
        '__ALPHA_ROUTER_ATTACH_JSON__:{"userText":"go","attachments":[{"name":"data.csv","kind":"document",'
        '"mime_type":"text/csv","url":"","text":"x,y\\n1,2"}]}'
    )
    files = workspace_files_from_messages([{"role": "user", "content": payload}])
    assert "data.csv" in files


def test_workspace_spreadsheet_attachments_renamed_to_csv():
    payload = (
        '__ALPHA_ROUTER_ATTACH_JSON__:{"userText":"analyze","attachments":[{'
        '"name":"Report Q1.xlsx","kind":"document","mime_type":'
        '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",'
        '"url":"","text":"name,value\\na,1\\nb,2"}]}'
    )
    files = workspace_files_from_messages([{"role": "user", "content": payload}])
    assert "Report Q1.csv" in files
    assert "Report Q1.xlsx" not in files
    assert files["Report Q1.csv"].startswith("name,value")


def test_workspace_spreadsheet_section_renamed_to_csv():
    messages = [
        {
            "role": "user",
            "content": "Analyze\n\n--- sales.xlsx ---\nname,value\na,1\nb,2",
        }
    ]
    files = workspace_files_from_messages(messages)
    assert files["sales.csv"].startswith("name,value")
    assert "sales.xlsx" not in files


def test_workspace_keeps_non_english_filenames():
    messages = [
        {
            "role": "user",
            "content": (
                "Analyze\n\n--- داده (1).csv ---\nname,value\na,1\nb,2\n\n"
                "--- report (2).csv ---\nx,y\n3,4"
            ),
        }
    ]
    files = workspace_files_from_messages(messages)
    assert set(files) == {"داده (1).csv", "report (2).csv"}
    for name in files:
        assert sanitize_workspace_filename(name) == name
        assert is_safe_filename(name)


def test_workspace_folds_only_unsafe_filename_characters():
    assert sanitize_workspace_filename("پوشه/گزارش نهایی.csv") == "گزارش نهایی.csv"
    assert sanitize_workspace_filename("report\u202efdp.csv") == "report_fdp.csv"
    assert sanitize_workspace_filename(".hidden.csv") == "hidden.csv"
    assert sanitize_workspace_filename("2026.csv") == "data_2026.csv"


def test_workspace_filename_stays_within_the_byte_budget():
    name = f"{'گ' * 400}.csv"
    safe = sanitize_workspace_filename(name)
    assert is_safe_filename(safe)
    assert safe.endswith(".csv")
    assert safe.startswith("گ")


def test_workspace_inventory_lists_exact_filenames():
    msg = code_interpreter_workspace_message({"sales.csv": "a,b\n1,2"})
    assert "sales.csv" in msg
    assert "exact filenames" in msg


def _artifact_payload(name: str, content: bytes, mime_type: str) -> dict:
    return {
        "name": name,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def test_decode_broker_artifacts_accepts_valid_pdf_and_csv():
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    csv = b"name,value\nalpha,1\n"
    artifacts = cis._decode_broker_artifacts(
        [
            _artifact_payload("report.pdf", pdf, "application/pdf"),
            _artifact_payload("table.csv", csv, "text/csv"),
        ]
    )
    assert [item.name for item in artifacts] == ["report.pdf", "table.csv"]
    assert artifacts[0].content == pdf
    assert artifacts[1].sha256 == hashlib.sha256(csv).hexdigest()


def test_decode_broker_artifacts_accepts_persian_filenames():
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    artifacts = cis._decode_broker_artifacts(
        [_artifact_payload("گزارش-مدیریتی.pdf", pdf, "application/pdf")]
    )
    assert [item.name for item in artifacts] == ["گزارش-مدیریتی.pdf"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.update(name="../report.pdf"),
        lambda item: item.update(name="report\u202efdp.pdf"),
        lambda item: item.update(name="report\x00.pdf"),
        lambda item: item.update(mime_type="text/html"),
        lambda item: item.update(sha256="0" * 64),
        lambda item: item.update(content_base64="not-base64"),
    ],
)
def test_decode_broker_artifacts_rejects_tampering(mutate):
    pdf = b"%PDF-1.4\n%%EOF"
    item = _artifact_payload("report.pdf", pdf, "application/pdf")
    mutate(item)
    with pytest.raises(ValueError):
        cis._decode_broker_artifacts([item])


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
        return SandboxExecutionResult(output="sub-ok", exit_code=0)

    async def fake_broker(code, files, settings, broker_url):
        calls["broker"] += 1
        return SandboxExecutionResult(output="broker-ok", exit_code=0)

    monkeypatch.setattr(cis, "_run_in_subprocess", fake_sub)
    monkeypatch.setattr(cis, "_run_via_broker", fake_broker)

    out = asyncio.run(run_python_sandbox("print(1)"))
    assert out.output == "sub-ok"
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
    assert "sandbox broker is required" in out.output
    _clear_settings_cache()


def test_legacy_image_only_configuration_cannot_downgrade(monkeypatch):
    monkeypatch.delenv("CODE_SANDBOX_BROKER_URL", raising=False)
    monkeypatch.setenv("CODE_SANDBOX_IMAGE", "alpha-router-sandbox:latest")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_INSECURE_CODE_SUBPROCESS", "true")
    _clear_settings_cache()

    async def forbidden_subprocess(code, files):
        raise AssertionError("legacy image config must not downgrade")

    monkeypatch.setattr(cis, "_run_in_subprocess", forbidden_subprocess)
    out = asyncio.run(run_python_sandbox("print(1)"))
    assert "legacy sandbox image configuration" in out.output
    _clear_settings_cache()


def test_run_sandbox_uses_broker_when_configured(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
    monkeypatch.setenv("CODE_SANDBOX_BROKER_TOKEN", "t" * 48)
    _clear_settings_cache()

    captured = {}

    async def fake_broker(code, files, settings, broker_url):
        captured["broker_url"] = broker_url
        captured["code"] = code
        return SandboxExecutionResult(output="broker-ok", exit_code=0)

    monkeypatch.setattr(cis, "_run_via_broker", fake_broker)

    out = asyncio.run(run_python_sandbox("print(2)", {"a.txt": "hi"}))
    assert out.output == "broker-ok"
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
    assert "broker authentication is not configured" in out.output
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
    assert "ok" in out.output
    assert "SECRET_KEY" not in captured["env"]
    assert set(captured["env"]) == {"PATH", "PYTHONIOENCODING", "PYTHONUNBUFFERED"}


async def _broker_status_maps_to_distinct_message(status: int, detail: str, needle: str) -> None:
    class FakeResponse:
        status_code = status
        headers = {}

        def json(self):
            return {"detail": detail}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def post(self, *args, **kwargs):
            del args, kwargs
            return FakeResponse()

    import httpx

    monkey_settings = type(
        "S",
        (),
        {
            "code_sandbox_timeout_seconds": 20,
            "code_sandbox_broker_token": "t" * 48,
        },
    )()
    original = httpx.AsyncClient
    httpx.AsyncClient = FakeClient  # type: ignore[misc,assignment]
    try:
        out = await cis._run_via_broker("print(1)", {}, monkey_settings, "http://broker")
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]
    assert needle in out.output
    if status in {429, 502, 503}:
        assert detail in out.output


def test_broker_http_errors_are_distinct(monkeypatch):
    del monkeypatch
    cases = [
        (401, "Unauthorized", "authentication failed"),
        (422, "Invalid workspace filename", "rejected the workspace payload"),
        (429, "Sandbox capacity is busy", "capacity is busy"),
        (502, "Sandbox execution failed", "container failed"),
        (503, "Sandbox image unavailable", "runtime unavailable"),
        (418, "teapot", "HTTP 418"),
    ]
    for status, detail, needle in cases:
        asyncio.run(_broker_status_maps_to_distinct_message(status, detail, needle))
