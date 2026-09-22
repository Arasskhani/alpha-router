"""Security policy tests for the internal sandbox broker."""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import sandbox_broker as broker

TOKEN = "t" * 48


def _client() -> TestClient:
    return TestClient(broker.app)


def test_compose_prepares_sandbox_before_starting_broker() -> None:
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    sandbox_section = compose.split("  alpha-router-sandbox:", 1)[1].split("  alpha-router-sandbox-broker:", 1)[0]
    broker_section = compose.split("  alpha-router-sandbox-broker:", 1)[1].split("  alpha-router:", 1)[0]
    assert 'entrypoint: ["/bin/true"]' in sandbox_section
    assert 'network_mode: "none"' in sandbox_section
    assert "profiles:" not in sandbox_section
    assert "condition: service_completed_successfully" in broker_section


def test_broker_rejects_missing_and_wrong_tokens() -> None:
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        client = _client()
        assert client.post("/v1/execute", json={"code": "print(1)"}).status_code == 401
        assert (
            client.post(
                "/v1/execute",
                json={"code": "print(1)"},
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )


def test_broker_fails_closed_without_configured_token() -> None:
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": ""}):
        response = _client().post(
            "/v1/execute",
            json={"code": "print(1)"},
            headers={"Authorization": "Bearer anything"},
        )
    assert response.status_code == 503


def test_broker_accepts_token_and_returns_sandbox_result() -> None:
    result = {"stdout": "42\n", "stderr": "", "exit_code": 0}
    with (
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "_run_container", AsyncMock(return_value=result)),
    ):
        response = _client().post(
            "/v1/execute",
            json={"code": "print(6*7)", "files": {"data.txt": "ok"}},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 200
    assert response.json() == result


def _artifact_payload(name: str, content: bytes, mime_type: str) -> dict:
    return {
        "name": name,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def test_broker_returns_artifacts_with_non_english_names() -> None:
    pdf = b"%PDF-1.4\n%%EOF"
    artifacts = broker._validated_artifacts([_artifact_payload("گزارش-مدیریتی.pdf", pdf, "application/pdf")])
    assert [item["name"] for item in artifacts] == ["گزارش-مدیریتی.pdf"]


def test_broker_validates_artifacts_before_returning_them() -> None:
    pdf = b"%PDF-1.4\n%%EOF"
    item = _artifact_payload("report.pdf", pdf, "application/pdf")
    assert broker._validated_artifacts([item]) == [item]

    tampered = dict(item, sha256="0" * 64)
    with pytest.raises(ValueError, match="digest"):
        broker._validated_artifacts([tampered])

    unsafe = dict(item, name="../report.pdf")
    with pytest.raises(ValueError, match="filename"):
        broker._validated_artifacts([unsafe])


async def test_broker_lifespan_smoke_tests_runtime() -> None:
    with patch.object(
        broker,
        "_run_container",
        AsyncMock(return_value={"stdout": "ready", "stderr": "", "exit_code": 0}),
    ) as execute:
        async with broker._lifespan(broker.app):
            assert broker._runtime_ready
        assert not broker._runtime_ready
        execute.assert_awaited_once()


async def test_health_rejects_before_runtime_smoke_test() -> None:
    with (
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "_runtime_ready", False),
        pytest.raises(broker.HTTPException) as exc,
    ):
        await broker.health()
    assert exc.value.status_code == 503
    assert "not ready" in str(exc.value.detail)


async def test_broker_rejects_saturated_queue_with_bounded_wait() -> None:
    saturated = asyncio.Semaphore(0)
    with (
        patch.object(broker, "_semaphore", saturated),
        patch.object(broker, "QUEUE_TIMEOUT_SECONDS", 0.01),
        pytest.raises(broker.HTTPException) as exc,
    ):
        await broker.execute(broker.ExecuteRequest(code="print(1)"))
    assert exc.value.status_code == 429


@pytest.mark.parametrize("field", ["image", "privileged", "mounts", "network", "command"])
def test_broker_rejects_policy_injection_fields(field: str) -> None:
    body = {"code": "print(1)", field: "attacker-controlled"}
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        response = _client().post(
            "/v1/execute",
            json=body,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 422


@pytest.mark.parametrize("filename", ["گزارش.csv", "خلاصه‌فاکتورها.txt", "отчет.json"])
def test_broker_accepts_non_english_workspace_filenames(filename: str) -> None:
    request = broker.ExecuteRequest(code="print(1)", files={filename: "x"})
    assert set(request.files) == {filename}


@pytest.mark.parametrize(
    "filename",
    [
        "../secret",
        "/etc/passwd",
        "a/b.txt",
        "a\\b.txt",
        "..",
        "report\u202efdp.txt",
        ".hidden.txt",
    ],
)
def test_broker_rejects_unsafe_filenames(filename: str) -> None:
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        response = _client().post(
            "/v1/execute",
            json={"code": "print(1)", "files": {filename: "x"}},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 422


def test_broker_rejects_file_count_and_size_limits() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with (
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "HARD_MAX_WORKSPACE_FILES", 10),
        patch.object(broker, "MAX_FILE_BYTES", 10),
    ):
        too_many = _client().post(
            "/v1/execute",
            json={
                "code": "print(1)",
                "files": {f"f{i}.txt": "x" for i in range(11)},
            },
            headers=headers,
        )
        too_large = _client().post(
            "/v1/execute",
            json={
                "code": "print(1)",
                "files": {"large.txt": "x" * 11},
            },
            headers=headers,
        )
    assert too_many.status_code == 422
    assert too_large.status_code == 422


def test_broker_accepts_one_hundred_small_workspace_files() -> None:
    request = broker.ExecuteRequest(
        code="print(1)",
        files={f"f{i}.txt": "x" for i in range(100)},
    )
    assert len(request.files) == 100


async def test_broker_authenticates_before_reading_request_body() -> None:
    received = False
    sent = []

    async def receive():
        nonlocal received
        received = True
        raise AssertionError("unauthenticated body must not be read")

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/execute",
        "raw_path": b"/v1/execute",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("broker", 8081),
    }
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        await broker.app(scope, receive, send)
    assert not received
    assert sent[0]["status"] == 401


async def test_broker_caps_streamed_body_without_content_length() -> None:
    sent = []
    test_limit = 1024
    chunks = [
        b"x" * (test_limit // 2),
        b"x" * (test_limit // 2 + 1),
    ]

    async def receive():
        body = chunks.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)

    async def drain_app(scope, receive, send):
        del scope
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/execute",
        "raw_path": b"/v1/execute",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {TOKEN}".encode())],
        "client": ("127.0.0.1", 1234),
        "server": ("broker", 8081),
    }
    with (
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "MAX_REQUEST_BYTES", test_limit),
    ):
        middleware = broker.BrokerSecurityMiddleware(drain_app)
        await middleware(scope, receive, send)
    assert any(message.get("status") == 413 for message in sent)


class _Writer:
    def __init__(self):
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Process:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self.stdin = _Writer()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.returncode = returncode
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


async def test_broker_hardcodes_container_security_policy() -> None:
    envelope = json.dumps({"stdout": "ok", "stderr": "", "exit_code": 0}).encode()
    captured: tuple[str, ...] = ()
    process = None

    async def fake_spawn(*args, **kwargs):
        nonlocal captured, process
        del kwargs
        captured = args
        process = _Process(envelope)
        return process

    async def run():
        with patch.object(asyncio, "create_subprocess_exec", fake_spawn):
            return await broker._run_container(broker.ExecuteRequest(code="print(1)", files={"data.txt": "ok"}))

    result = await run()
    assert result["stdout"] == "ok"
    assert captured[-1] == broker.SANDBOX_IMAGE
    assert broker.SANDBOX_IMAGE == "alpha-router-sandbox:latest"
    assert captured[captured.index("--name") + 1].startswith("alpha-router-sandbox-")
    assert captured[captured.index("--label") + 1] == "com.alpha-router.sandbox=true"
    assert "--network" in captured and "none" in captured
    assert "--read-only" in captured
    assert "--cap-drop" in captured and "ALL" in captured
    assert "--security-opt" in captured and "no-new-privileges" in captured
    assert "--user" in captured and "65534:65534" in captured
    assert "--memory" in captured and "256m" in captured
    assert "--pids-limit" in captured and "128" in captured
    assert "--privileged" not in captured
    assert "--volume" not in captured and "-v" not in captured
    assert process is not None
    payload = json.loads(process.stdin.data)
    assert set(payload) == {"code", "files"}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_broker_accepts_valid_base64_binary_workspace_files() -> None:
    blob = bytes(range(256))
    request = broker.ExecuteRequest(code="print(1)", files_b64={"blob.bin": _b64(blob)})
    assert request.files_b64 == {"blob.bin": _b64(blob)}
    assert request.files == {}


@pytest.mark.parametrize("encoded", ["not base64!", "AQ", "AQ==ID", "AQID\n"])
def test_broker_rejects_invalid_base64_binary_workspace_files(encoded: str) -> None:
    with pytest.raises(ValidationError, match="Invalid base64 workspace file"):
        broker.ExecuteRequest(code="print(1)", files_b64={"blob.bin": encoded})


@pytest.mark.parametrize("filename", ["../secret", "a/b.bin", ".hidden.bin", "report‮fdp.bin"])
def test_broker_rejects_unsafe_binary_workspace_filenames(filename: str) -> None:
    with pytest.raises(ValidationError, match="Invalid workspace filename"):
        broker.ExecuteRequest(code="print(1)", files_b64={filename: "AQID"})


def test_broker_limits_binary_workspace_file_by_decoded_size() -> None:
    with patch.object(broker, "MAX_FILE_BYTES", 10):
        # 10 decoded bytes is 16 base64 characters: the limit is on the bytes,
        # not on the encoded string, so this must pass.
        assert broker.ExecuteRequest(code="print(1)", files_b64={"ok.bin": _b64(b"x" * 10)}).files_b64
        with pytest.raises(ValidationError, match="Workspace file exceeds size limit"):
            broker.ExecuteRequest(code="print(1)", files_b64={"big.bin": _b64(b"x" * 11)})


def test_broker_total_size_limit_spans_text_and_binary_files() -> None:
    with patch.object(broker, "MAX_TOTAL_FILE_BYTES", 100), patch.object(broker, "MAX_FILE_BYTES", 100):
        text_part = {"text.txt": "x" * 60}
        binary_part = {"blob.bin": _b64(b"\x00" * 60)}
        assert broker.ExecuteRequest(code="print(1)", files=text_part).files == text_part
        assert broker.ExecuteRequest(code="print(1)", files_b64=binary_part).files_b64 == binary_part
        with pytest.raises(ValidationError, match="Workspace files exceed total size limit"):
            broker.ExecuteRequest(code="print(1)", files=text_part, files_b64=binary_part)


def test_broker_file_count_limit_spans_text_and_binary_files() -> None:
    with patch.object(broker, "HARD_MAX_WORKSPACE_FILES", 10):
        text_part = {f"t{i}.txt": "x" for i in range(6)}
        binary_part = {f"b{i}.bin": "AQID" for i in range(6)}
        assert len(broker.ExecuteRequest(code="print(1)", files=text_part).files) == 6
        assert len(broker.ExecuteRequest(code="print(1)", files_b64=binary_part).files_b64) == 6
        with pytest.raises(ValidationError, match="Workspace file count exceeds the hard limit"):
            broker.ExecuteRequest(code="print(1)", files=text_part, files_b64=binary_part)


def test_broker_rejects_same_filename_in_text_and_binary_maps() -> None:
    with pytest.raises(ValidationError, match="duplicate workspace filename"):
        broker.ExecuteRequest(code="print(1)", files={"data.csv": "a,b"}, files_b64={"data.csv": "AQID"})


def test_broker_legacy_execute_accepts_and_validates_files_b64() -> None:
    result = {"stdout": "", "stderr": "", "exit_code": 0}
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with (
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "_run_container", AsyncMock(return_value=result)) as run,
    ):
        ok = _client().post("/v1/execute", json={"code": "print(1)", "files_b64": {"a.bin": "AQID"}}, headers=headers)
        bad = _client().post("/v1/execute", json={"code": "print(1)", "files_b64": {"a.bin": "!!"}}, headers=headers)
    assert ok.status_code == 200
    assert run.await_args.args[0].files_b64 == {"a.bin": "AQID"}
    assert bad.status_code == 422


async def _captured_stdin_payload(request: broker.ExecuteRequest) -> bytes:
    envelope = json.dumps({"stdout": "ok", "stderr": "", "exit_code": 0}).encode()
    process = None

    async def fake_spawn(*args, **kwargs):
        nonlocal process
        del args, kwargs
        process = _Process(envelope)
        return process

    with patch.object(asyncio, "create_subprocess_exec", fake_spawn):
        await broker._run_container(request)
    assert process is not None
    return process.stdin.data


async def test_broker_stdin_payload_carries_files_b64_verbatim() -> None:
    encoded = _b64(bytes(range(256)))
    raw = await _captured_stdin_payload(
        broker.ExecuteRequest(code="print(1)", files={"a.txt": "hi"}, files_b64={"blob.bin": encoded})
    )
    payload = json.loads(raw)
    assert set(payload) == {"code", "files", "files_b64"}
    assert payload["files_b64"] == {"blob.bin": encoded}
    assert payload["files"] == {"a.txt": "hi"}


async def test_broker_stdin_payload_is_byte_identical_without_binaries() -> None:
    raw = await _captured_stdin_payload(broker.ExecuteRequest(code="print(1)", files={"a.txt": "hi"}))
    # The exact bytes an older runner image received before the binary channel
    # existed; any new key would break that guarantee.
    assert raw == json.dumps({"code": "print(1)", "files": {"a.txt": "hi"}}, ensure_ascii=False).encode("utf-8")
    assert b"files_b64" not in raw


async def test_broker_force_removes_container_after_unexpected_io_failure() -> None:
    process = None

    async def fake_spawn(*args, **kwargs):
        nonlocal process
        del args, kwargs
        process = _Process(b"")
        return process

    async def run():
        with (
            patch.object(asyncio, "create_subprocess_exec", fake_spawn),
            patch.object(broker, "_exchange", AsyncMock(side_effect=RuntimeError("io failed"))),
            patch.object(broker, "_force_remove", AsyncMock()) as force_remove,
        ):
            with pytest.raises(RuntimeError, match="io failed"):
                await broker._run_container(broker.ExecuteRequest(code="print(1)"))
            force_remove.assert_awaited_once()

    await run()
    assert process is not None
    assert process.killed
