"""Internal authenticated broker for disposable code-interpreter containers."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import re
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

SANDBOX_IMAGE = "nitro-sandbox:latest"
MAX_REQUEST_BYTES = 3 * 1024 * 1024
MAX_CODE_CHARS = 100_000
MAX_FILES = 10
MAX_FILE_BYTES = 512_000
MAX_TOTAL_FILE_BYTES = 2 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 512_000
MAX_RESULT_CHARS = 200_000
EXECUTION_TIMEOUT_SECONDS = 30
QUEUE_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_SANDBOXES = 4
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

app = FastAPI(
    title="NITRO Sandbox Broker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def validate_files(cls, files: dict[str, str]) -> dict[str, str]:
        if len(files) > MAX_FILES:
            raise ValueError(f"At most {MAX_FILES} files are allowed")
        total = 0
        for name, content in files.items():
            if not _SAFE_FILENAME.fullmatch(name) or "/" in name or "\\" in name or name in {".", ".."}:
                raise ValueError("Invalid workspace filename")
            size = len(content.encode("utf-8"))
            if size > MAX_FILE_BYTES:
                raise ValueError("Workspace file exceeds size limit")
            total += size
        if total > MAX_TOTAL_FILE_BYTES:
            raise ValueError("Workspace files exceed total size limit")
        return files


def _authorize(authorization: str | None) -> None:
    expected = (os.environ.get("SANDBOX_BROKER_TOKEN") or "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="Sandbox broker token is not configured")
    scheme, separator, supplied = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not hmac.compare_digest(supplied.strip(), expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


class _RequestTooLarge(Exception):
    pass


class BrokerSecurityMiddleware:
    """Authenticate before body parsing and cap streamed request bytes."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/v1/execute":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        try:
            _authorize(headers.get("authorization"))
        except HTTPException as exc:
            response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            await response(scope, receive, send)
            return

        raw_length = headers.get("content-length")
        if raw_length:
            with contextlib.suppress(ValueError):
                if int(raw_length) > MAX_REQUEST_BYTES:
                    response = JSONResponse(status_code=413, content={"detail": "Request too large"})
                    await response(scope, receive, send)
                    return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > MAX_REQUEST_BYTES:
                    raise _RequestTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            response = JSONResponse(status_code=413, content={"detail": "Request too large"})
            await response(scope, receive, send)


app.add_middleware(BrokerSecurityMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/execute")
async def execute(body: ExecuteRequest) -> dict[str, str | int]:
    try:
        await asyncio.wait_for(_semaphore.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(status_code=429, detail="Sandbox capacity is busy") from None
    try:
        return await _run_container(body)
    finally:
        _semaphore.release()


class _OutputLimitExceeded(RuntimeError):
    pass


async def _read_limited(stream: asyncio.StreamReader, limit: int) -> bytes:
    output = bytearray()
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return bytes(output)
        output.extend(chunk)
        if len(output) > limit:
            raise _OutputLimitExceeded()


async def _exchange(
    proc: asyncio.subprocess.Process,
    payload: bytes,
) -> tuple[bytes, bytes]:
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None
    proc.stdin.write(payload)
    await proc.stdin.drain()
    proc.stdin.close()
    stdout_task = asyncio.create_task(_read_limited(proc.stdout, MAX_PROCESS_OUTPUT_BYTES))
    stderr_task = asyncio.create_task(_read_limited(proc.stderr, MAX_PROCESS_OUTPUT_BYTES))
    try:
        stdout_b, stderr_b = await asyncio.gather(stdout_task, stderr_task)
        await proc.wait()
        return stdout_b, stderr_b
    except BaseException:
        for task in (stdout_task, stderr_task):
            task.cancel()
        raise


async def _force_remove(container_name: str) -> None:
    with contextlib.suppress(Exception):
        cleanup = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(cleanup.wait(), timeout=5)


async def _run_container(body: ExecuteRequest) -> dict[str, str | int]:
    container_name = f"nitro-sandbox-{uuid.uuid4().hex}"
    payload = json.dumps(
        {"code": body.code, "files": body.files},
        ensure_ascii=False,
    ).encode("utf-8")
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        container_name,
        "--label",
        "nitro.sandbox=true",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=64m",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--pids-limit",
        "128",
        "--cpus",
        "1.0",
        "--ulimit",
        "nofile=64:64",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--log-driver",
        "none",
        SANDBOX_IMAGE,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Sandbox runtime unavailable") from exc

    completed = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            _exchange(proc, payload),
            timeout=EXECUTION_TIMEOUT_SECONDS,
        )
        completed = True
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(status_code=504, detail="Sandbox execution timed out") from None
    except _OutputLimitExceeded:
        raise HTTPException(status_code=413, detail="Sandbox output exceeds limit") from None
    finally:
        if not completed:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
            await _force_remove(container_name)

    raw_out = stdout_b.decode("utf-8", errors="replace").strip()
    raw_err = stderr_b.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or not raw_out:
        raise HTTPException(status_code=502, detail="Sandbox execution failed")
    try:
        result = json.loads(raw_out.splitlines()[-1])
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Invalid sandbox response") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Invalid sandbox response")

    stdout = str(result.get("stdout") or "")[:MAX_RESULT_CHARS]
    stderr = str(result.get("stderr") or "")[:MAX_RESULT_CHARS]
    try:
        exit_code = int(result.get("exit_code") or 0)
    except (TypeError, ValueError):
        exit_code = 1
    if raw_err and not stderr:
        stderr = "Sandbox runtime reported an error"
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
