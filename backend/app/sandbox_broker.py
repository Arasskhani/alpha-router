"""Internal authenticated broker for disposable code-interpreter containers."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import datetime
import hashlib
import hmac
import json
import logging
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.branding import PRODUCT_NAME
from app.sandbox.contracts import (
    CapacityStatus,
    ErrorCode,
    JobCancelResponse,
    JobState,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    ResultCode,
    SandboxResult,
    can_transition,
    is_terminal,
)
from app.sandbox.filenames import is_safe_filename


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


SANDBOX_IMAGE = "alpha-router-sandbox:latest"
SANDBOX_LABEL = "com.alpha-router.sandbox=true"
MAX_REQUEST_BYTES = _int_env("SANDBOX_HARD_MAX_REQUEST_BYTES", 72 * 1024 * 1024)
MAX_CODE_CHARS = 100_000
MAX_FILE_BYTES = _int_env("SANDBOX_HARD_MAX_WORKSPACE_FILE_BYTES", 64 * 1024 * 1024)
MAX_TOTAL_FILE_BYTES = _int_env("SANDBOX_HARD_MAX_WORKSPACE_TOTAL_BYTES", 64 * 1024 * 1024)
MAX_PROCESS_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_RESULT_CHARS = 200_000
MAX_ARTIFACTS = 5
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 10 * 1024 * 1024
EXECUTION_TIMEOUT_SECONDS = 30

# Capacity + admission control. These honor the compose-managed environment
# contract (SANDBOX_MAX_CONCURRENT, SANDBOX_QUEUE_TIMEOUT_SECONDS,
# SANDBOX_RETRY_AFTER_SECONDS) with safe fallbacks for local/dev runs.
MAX_CONCURRENT_SANDBOXES = _int_env("SANDBOX_MAX_CONCURRENT", 200)
QUEUE_TIMEOUT_SECONDS = _float_env("SANDBOX_QUEUE_TIMEOUT_SECONDS", 0.1)
RETRY_AFTER_SECONDS = _int_env("SANDBOX_RETRY_AFTER_SECONDS", 30)
# Absolute infrastructure guard. Product policy is validated upstream from the
# Admin-managed workspace limits; the broker only rejects pathological payloads.
HARD_MAX_WORKSPACE_FILES = _int_env("SANDBOX_HARD_MAX_WORKSPACE_FILES", 1000)

# Terminal jobs are retained briefly so clients can read their result, then
# reaped to bound memory. The store is also hard-capped.
JOB_RETENTION_SECONDS = _int_env("SANDBOX_JOB_RETENTION_SECONDS", 300)
MAX_TRACKED_JOBS = _int_env("SANDBOX_MAX_TRACKED_JOBS", 10_000)

_ARTIFACT_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)
logger = logging.getLogger(__name__)
_runtime_ready = False


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Verify the Docker execution path once before advertising readiness."""
    global _runtime_ready
    await _cleanup_orphans()
    try:
        result = await _run_container(ExecuteRequest(code="print('ready')"))
        if result.get("exit_code") != 0 or str(result.get("stdout") or "").strip() != "ready":
            raise RuntimeError("Sandbox smoke test returned an unexpected result")
    except Exception as exc:
        logger.exception("Sandbox runtime smoke test failed")
        raise RuntimeError("Sandbox runtime smoke test failed") from exc
    _runtime_ready = True
    try:
        yield
    finally:
        _runtime_ready = False
        await _shutdown_jobs()


app = FastAPI(
    title=f"{PRODUCT_NAME} Sandbox Broker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def validate_files(cls, files: dict[str, str]) -> dict[str, str]:
        if len(files) > HARD_MAX_WORKSPACE_FILES:
            raise ValueError("Workspace file count exceeds the hard limit")
        total = 0
        for name, content in files.items():
            if not is_safe_filename(name):
                raise ValueError("Invalid workspace filename")
            size = len(content.encode("utf-8"))
            if size > MAX_FILE_BYTES:
                raise ValueError("Workspace file exceeds size limit")
            total += size
        if total > MAX_TOTAL_FILE_BYTES:
            raise ValueError("Workspace files exceed total size limit")
        return files


def _validate_artifact_content(name: str, content: bytes) -> None:
    suffix = os.path.splitext(name)[1].lower()
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise ValueError("Invalid PDF artifact")
        return
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Artifact text must be UTF-8") from exc
    if "\x00" in text:
        raise ValueError("Artifact text contains NUL bytes")
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON artifact") from exc


def _validated_artifacts(value: object) -> list[dict[str, str | int]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ARTIFACTS:
        raise ValueError("Invalid artifact list")

    total = 0
    validated: list[dict[str, str | int]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid artifact entry")
        name = item.get("name")
        mime_type = item.get("mime_type")
        encoded = item.get("content_base64")
        digest = item.get("sha256")
        size_bytes = item.get("size_bytes")
        if not is_safe_filename(name):
            raise ValueError("Invalid artifact filename")
        suffix = os.path.splitext(name)[1].lower()
        expected_mime = _ARTIFACT_MIME_BY_SUFFIX.get(suffix)
        if not expected_mime or mime_type != expected_mime:
            raise ValueError("Invalid artifact MIME type")
        if not isinstance(encoded, str) or not isinstance(digest, str):
            raise ValueError("Invalid artifact payload")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise ValueError("Invalid artifact size")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise ValueError("Invalid artifact encoding") from exc
        if not content or len(content) != size_bytes or len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("Invalid artifact size")
        total += len(content)
        if total > MAX_TOTAL_ARTIFACT_BYTES:
            raise ValueError("Artifact aggregate exceeds limit")
        actual_digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(actual_digest, digest.lower()):
            raise ValueError("Invalid artifact digest")
        _validate_artifact_content(name, content)
        validated.append(
            {
                "name": name,
                "mime_type": expected_mime,
                "size_bytes": len(content),
                "sha256": actual_digest,
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    return validated


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
        if scope["type"] != "http" or not str(scope.get("path") or "").startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        try:
            _authorize(headers.get("authorization"))
        except HTTPException as exc:
            content: dict[str, object] = {"detail": exc.detail}
            if exc.status_code == 401:
                content["error_code"] = ErrorCode.NOT_AUTHORIZED.value
            response = JSONResponse(status_code=exc.status_code, content=content)
            await response(scope, receive, send)
            return

        raw_length = headers.get("content-length")
        if raw_length:
            with contextlib.suppress(ValueError):
                if int(raw_length) > MAX_REQUEST_BYTES:
                    await _too_large_response(scope, receive, send)
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
            await _too_large_response(scope, receive, send)


async def _too_large_response(scope, receive, send) -> None:
    response = JSONResponse(
        status_code=413,
        content={
            "detail": "Request too large",
            "error_code": ErrorCode.REQUEST_TOO_LARGE.value,
        },
    )
    await response(scope, receive, send)


app.add_middleware(BrokerSecurityMiddleware)


async def _check_readiness() -> dict[str, str]:
    """Shared readiness gate: auth configured, runtime smoke-tested, image present."""
    if len((os.environ.get("SANDBOX_BROKER_TOKEN") or "").strip()) < 32:
        raise HTTPException(status_code=503, detail="Broker authentication is not configured")
    if not _runtime_ready:
        raise HTTPException(status_code=503, detail="Sandbox runtime is not ready")
    try:
        check = await asyncio.create_subprocess_exec(
            "docker",
            "image",
            "inspect",
            SANDBOX_IMAGE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(check.wait(), timeout=3)
    except (FileNotFoundError, TimeoutError):
        raise HTTPException(status_code=503, detail="Sandbox runtime unavailable") from None
    if check.returncode != 0:
        raise HTTPException(status_code=503, detail="Sandbox image unavailable")
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    return await _check_readiness()


@app.get("/livez")
async def livez() -> dict[str, str]:
    """Liveness: the process is up and serving. No external dependencies."""
    return {"status": "alive"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness: safe to route traffic (auth + runtime + image)."""
    return await _check_readiness()


@app.post("/v1/execute")
async def execute(body: ExecuteRequest) -> dict[str, object]:
    try:
        await asyncio.wait_for(_semaphore.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except TimeoutError:
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


async def _run_container(body: ExecuteRequest, job: _Job | None = None) -> dict[str, object]:
    container_name = f"alpha-router-sandbox-{uuid.uuid4().hex}"
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
        SANDBOX_LABEL,
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

    if job is not None:
        # Register the live process/container so DELETE can kill it, and mark the
        # job RUNNING now that a container actually exists.
        job.attach(proc, container_name)
        # DELETE can race with docker process creation. If cancellation won
        # before attach(), terminate the newly visible process immediately.
        if job.cancel_requested:
            await _terminate(proc, container_name)
            raise asyncio.CancelledError

    completed = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            _exchange(proc, payload),
            timeout=EXECUTION_TIMEOUT_SECONDS,
        )
        completed = True
    except TimeoutError:
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
    try:
        artifacts = _validated_artifacts(result.get("artifacts"))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid sandbox artifact response") from exc

    stdout = str(result.get("stdout") or "")[:MAX_RESULT_CHARS]
    stderr = str(result.get("stderr") or "")[:MAX_RESULT_CHARS]
    try:
        exit_code = int(result.get("exit_code") or 0)
    except (TypeError, ValueError):
        exit_code = 1
    if raw_err and not stderr:
        stderr = "Sandbox runtime reported an error"
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# Job lifecycle
#
# The additive job API layers an explicit, terminal state machine on top of the
# same isolated container runtime used by POST /v1/execute. Submission is
# no-queue: capacity is admitted immediately or rejected with 429 + Retry-After.
# ---------------------------------------------------------------------------


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclasses.dataclass
class _Job:
    job_id: str
    request: ExecuteRequest | None = None
    state: JobState = JobState.PENDING
    created_at: datetime.datetime = dataclasses.field(default_factory=_now)
    updated_at: datetime.datetime = dataclasses.field(default_factory=_now)
    process: asyncio.subprocess.Process | None = None
    container_name: str | None = None
    result: dict[str, object] | None = None
    result_code: ResultCode | None = None
    error_code: ErrorCode | None = None
    detail: str | None = None
    cancel_requested: bool = False
    released: bool = False
    task: asyncio.Task | None = None

    def set_state(self, target: JobState) -> bool:
        """Apply a guarded forward transition. Terminal states are immutable."""
        if self.state == target:
            return True
        if not can_transition(self.state, target):
            return False
        self.state = target
        self.updated_at = _now()
        return True

    def attach(self, proc: asyncio.subprocess.Process, container_name: str) -> None:
        self.process = proc
        self.container_name = container_name
        if self.state == JobState.PENDING and not self.cancel_requested:
            self.set_state(JobState.RUNNING)


_jobs: dict[str, _Job] = {}
_jobs_lock = asyncio.Lock()


def _release_once(job: _Job) -> None:
    """Release the capacity slot exactly once for this job.

    Both the execution task's ``finally`` and DELETE-driven cancellation may call
    this; the flag flip and ``release()`` happen without an ``await`` in between,
    so on the single-threaded event loop this is race-free.
    """
    if job.released:
        return
    job.released = True
    _semaphore.release()


async def _acquire_no_queue() -> bool:
    """Admit immediately if a slot is free, otherwise refuse (no queueing)."""
    if _semaphore.locked():
        return False
    await _semaphore.acquire()
    return True


async def _terminate(proc: asyncio.subprocess.Process | None, container_name: str | None) -> None:
    """Kill the docker CLI process and force-remove its container."""
    if proc is not None:
        with contextlib.suppress(Exception):
            proc.kill()
    if container_name:
        await _force_remove(container_name)


def _finish_success(job: _Job, result: dict[str, object]) -> None:
    if is_terminal(job.state):
        return
    try:
        exit_code = int(result.get("exit_code") or 0)
    except (TypeError, ValueError):
        exit_code = 1
    job.result = result
    job.result_code = ResultCode.OK if exit_code == 0 else ResultCode.NONZERO_EXIT
    job.set_state(JobState.SUCCEEDED)


def _finish_from_http(job: _Job, exc: HTTPException) -> None:
    if is_terminal(job.state):
        return
    detail = str(exc.detail)
    if exc.status_code == 504:
        job.error_code = ErrorCode.EXECUTION_TIMEOUT
        job.detail = detail
        job.set_state(JobState.TIMEOUT)
        return
    if exc.status_code == 413:
        job.error_code = ErrorCode.OUTPUT_LIMIT_EXCEEDED
    elif exc.status_code == 503:
        job.error_code = ErrorCode.SANDBOX_UNAVAILABLE
    elif exc.status_code == 502 and "Invalid" in detail:
        job.error_code = ErrorCode.INVALID_SANDBOX_RESPONSE
    else:
        job.error_code = ErrorCode.EXECUTION_FAILED
    job.detail = detail
    job.set_state(JobState.FAILED)


async def _run_job(job: _Job) -> None:
    try:
        if job.cancel_requested or job.request is None:
            return
        try:
            result = await _run_container(job.request, job=job)
        except HTTPException as exc:
            _finish_from_http(job, exc)
            return
        except asyncio.CancelledError:
            if not is_terminal(job.state):
                job.error_code = ErrorCode.CANCELLED
                job.set_state(JobState.CANCELLED)
            raise
        except Exception:
            logger.exception("Sandbox job %s failed unexpectedly", job.job_id)
            if not is_terminal(job.state):
                job.error_code = ErrorCode.EXECUTION_FAILED
                job.detail = "Sandbox execution failed"
                job.set_state(JobState.FAILED)
            return
        _finish_success(job, result)
    finally:
        _release_once(job)


def _reap_jobs_locked() -> None:
    if not _jobs:
        return
    now = _now()
    stale = [
        job_id
        for job_id, job in _jobs.items()
        if is_terminal(job.state) and (now - job.updated_at).total_seconds() > JOB_RETENTION_SECONDS
    ]
    for job_id in stale:
        _jobs.pop(job_id, None)


def _evict_oldest_terminal_locked() -> bool:
    terminal = [(job.updated_at, job_id) for job_id, job in _jobs.items() if is_terminal(job.state)]
    if not terminal:
        return False
    terminal.sort()
    _jobs.pop(terminal[0][1], None)
    return True


def _status_payload(job: _Job) -> JobStatusResponse:
    result_model = None
    if job.state == JobState.SUCCEEDED and job.result is not None:
        result_model = SandboxResult(
            stdout=str(job.result.get("stdout") or ""),
            stderr=str(job.result.get("stderr") or ""),
            exit_code=int(job.result.get("exit_code") or 0),
            artifacts=list(job.result.get("artifacts") or []),
        )
    return JobStatusResponse(
        job_id=job.job_id,
        state=job.state,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        result_code=job.result_code,
        error_code=job.error_code,
        detail=job.detail,
        result=result_model,
    )


def _error_json(status_code: int, error_code: ErrorCode, detail: str, **kwargs) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_code": error_code.value},
        **kwargs,
    )


@app.post("/v1/jobs")
async def submit_job(body: JobSubmitRequest):
    # Reuse the legacy ExecuteRequest validators as the single source of truth
    # for workspace file limits and code sizing.
    try:
        request = ExecuteRequest(code=body.code, files=body.files)
    except ValidationError:
        return _error_json(422, ErrorCode.INVALID_REQUEST, "Invalid job request")

    job_id = body.job_id or uuid.uuid4().hex

    async with _jobs_lock:
        _reap_jobs_locked()
        if job_id in _jobs:
            return _error_json(409, ErrorCode.JOB_ALREADY_EXISTS, "job_id already exists")
        if len(_jobs) >= MAX_TRACKED_JOBS and not _evict_oldest_terminal_locked():
            return _error_json(
                503,
                ErrorCode.CAPACITY_UNAVAILABLE,
                "Too many tracked jobs",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            )
        if not await _acquire_no_queue():
            return _error_json(
                429,
                ErrorCode.CAPACITY_UNAVAILABLE,
                "Sandbox capacity is unavailable",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            )
        job = _Job(job_id=job_id, request=request)
        _jobs[job_id] = job
        job.task = asyncio.create_task(_run_job(job))

    return JSONResponse(
        status_code=202,
        content=JobSubmitResponse(job_id=job_id, state=job.state).model_dump(),
    )


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str):
    async with _jobs_lock:
        _reap_jobs_locked()
        job = _jobs.get(job_id)
        if job is None:
            return _error_json(404, ErrorCode.JOB_NOT_FOUND, "Unknown job_id")
        payload = _status_payload(job)
    return JSONResponse(status_code=200, content=payload.model_dump())


@app.delete("/v1/jobs/{job_id}")
async def cancel_job(job_id: str):
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return _error_json(404, ErrorCode.JOB_NOT_FOUND, "Unknown job_id")
        if is_terminal(job.state):
            # Idempotent: report the settled terminal state without side effects.
            return JSONResponse(
                status_code=200,
                content=JobCancelResponse(job_id=job.job_id, state=job.state).model_dump(),
            )
        job.cancel_requested = True
        if job.error_code is None:
            job.error_code = ErrorCode.CANCELLED
        job.set_state(JobState.CANCELLED)
        proc = job.process
        container_name = job.container_name

    await _terminate(proc, container_name)
    _release_once(job)
    return JSONResponse(
        status_code=200,
        content=JobCancelResponse(job_id=job_id, state=JobState.CANCELLED).model_dump(),
    )


@app.get("/v1/capacity")
async def capacity() -> dict[str, object]:
    async with _jobs_lock:
        active = sum(1 for job in _jobs.values() if job.state in (JobState.PENDING, JobState.RUNNING))
        tracked = len(_jobs)
    available = max(0, int(getattr(_semaphore, "_value", 0)))
    in_use = max(0, MAX_CONCURRENT_SANDBOXES - available)
    return CapacityStatus(
        max_concurrent=MAX_CONCURRENT_SANDBOXES,
        in_use=in_use,
        available=available,
        active_jobs=active,
        tracked_jobs=tracked,
    ).model_dump()


async def _cleanup_orphans() -> None:
    """Remove any leftover sandbox containers from a previous crash, by label."""
    with contextlib.suppress(Exception):
        lister = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label={SANDBOX_LABEL}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout_b, _ = await asyncio.wait_for(lister.communicate(), timeout=5)
        ids = [line.strip() for line in stdout_b.decode("utf-8", "replace").splitlines() if line.strip()]
        if not ids:
            return
        remover = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            *ids,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(remover.wait(), timeout=10)
        logger.info("Removed %d orphaned sandbox container(s) on startup", len(ids))


async def _shutdown_jobs() -> None:
    """Best-effort cancellation of in-flight jobs during shutdown."""
    async with _jobs_lock:
        jobs = list(_jobs.values())
    for job in jobs:
        if is_terminal(job.state):
            continue
        job.cancel_requested = True
        if job.error_code is None:
            job.error_code = ErrorCode.CANCELLED
        job.set_state(JobState.CANCELLED)
        await _terminate(job.process, job.container_name)
        _release_once(job)
