"""Security policy tests for the internal sandbox broker."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import sandbox_broker as broker

TOKEN = "t" * 48


def _client() -> TestClient:
    return TestClient(broker.app)


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


def test_broker_rejects_saturated_queue_with_bounded_wait() -> None:
    async def run():
        saturated = asyncio.Semaphore(0)
        with (
            patch.object(broker, "_semaphore", saturated),
            patch.object(broker, "QUEUE_TIMEOUT_SECONDS", 0.01),
            pytest.raises(broker.HTTPException) as exc,
        ):
            await broker.execute(broker.ExecuteRequest(code="print(1)"))
        assert exc.value.status_code == 429

    asyncio.run(run())


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


@pytest.mark.parametrize("filename", ["../secret", "/etc/passwd", "a/b.txt", "a\\b.txt", ".."])
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
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        too_many = _client().post(
            "/v1/execute",
            json={
                "code": "print(1)",
                "files": {f"f{i}.txt": "x" for i in range(broker.MAX_FILES + 1)},
            },
            headers=headers,
        )
        too_large = _client().post(
            "/v1/execute",
            json={
                "code": "print(1)",
                "files": {"large.txt": "x" * (broker.MAX_FILE_BYTES + 1)},
            },
            headers=headers,
        )
    assert too_many.status_code == 422
    assert too_large.status_code == 422


def test_broker_authenticates_before_reading_request_body() -> None:
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
        asyncio.run(broker.app(scope, receive, send))
    assert not received
    assert sent[0]["status"] == 401


def test_broker_caps_streamed_body_without_content_length() -> None:
    sent = []
    chunks = [
        b"x" * (broker.MAX_REQUEST_BYTES // 2),
        b"x" * (broker.MAX_REQUEST_BYTES // 2 + 1),
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
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        middleware = broker.BrokerSecurityMiddleware(drain_app)
        asyncio.run(middleware(scope, receive, send))
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


def test_broker_hardcodes_container_security_policy() -> None:
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
            return await broker._run_container(
                broker.ExecuteRequest(code="print(1)", files={"data.txt": "ok"})
            )

    result = asyncio.run(run())
    assert result["stdout"] == "ok"
    assert broker.SANDBOX_IMAGE == captured[-1]
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


def test_broker_force_removes_container_after_unexpected_io_failure() -> None:
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

    asyncio.run(run())
    assert process is not None
    assert process.killed
