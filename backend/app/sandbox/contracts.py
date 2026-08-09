"""Wire contracts for the sandbox broker job lifecycle.

This module is intentionally free of runtime/asyncio state so it can be shared
between the broker process and any client-side consumer without importing the
FastAPI application. It defines:

* the explicit, terminal job state machine,
* stable structured error/result codes,
* the additive ``/v1/jobs`` request/response models,
* the capacity report model.

The legacy ``POST /v1/execute`` request model lives in ``app.sandbox_broker`` and
is intentionally left untouched for backward compatibility.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A client-supplied job_id must be safe for logging, labels, and URL paths.
_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class JobState(str, Enum):
    """Explicit lifecycle states for a sandbox execution job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# Terminal states never transition again. Any late completion/cancel signal that
# arrives after a job is terminal must be ignored to keep the machine explicit.
TERMINAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.TIMEOUT,
    }
)

# Allowed forward transitions. Enforced centrally so no code path can invent an
# illegal edge (e.g. terminal -> running).
_ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset(
        {
            JobState.RUNNING,
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMEOUT,
        }
    ),
    JobState.RUNNING: frozenset(
        {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMEOUT,
        }
    ),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
    JobState.TIMEOUT: frozenset(),
}


def is_terminal(state: JobState) -> bool:
    return state in TERMINAL_STATES


def can_transition(current: JobState, target: JobState) -> bool:
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


class ErrorCode(str, Enum):
    """Stable, machine-readable error codes returned to broker clients."""

    CAPACITY_UNAVAILABLE = "capacity_unavailable"
    EXECUTION_TIMEOUT = "execution_timeout"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    INVALID_SANDBOX_RESPONSE = "invalid_sandbox_response"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"
    JOB_NOT_FOUND = "job_not_found"
    JOB_ALREADY_EXISTS = "job_already_exists"
    INVALID_REQUEST = "invalid_request"
    NOT_AUTHORIZED = "not_authorized"
    REQUEST_TOO_LARGE = "request_too_large"


class ResultCode(str, Enum):
    """Structured result codes for terminal, non-error outcomes."""

    OK = "ok"
    NONZERO_EXIT = "nonzero_exit"


class JobSubmitRequest(BaseModel):
    """Additive submit payload for ``POST /v1/jobs``.

    Unknown fields are rejected (``extra="forbid"``) to preserve the same
    policy-injection defense as ``/v1/execute``. Per-file size/count limits are
    enforced by the broker via the legacy ``ExecuteRequest`` validators so there
    is a single source of truth for workspace validation.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str | None = None
    code: str = Field(min_length=1)
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not _JOB_ID_PATTERN.fullmatch(value):
            raise ValueError("Invalid job_id")
        return value


class SandboxResult(BaseModel):
    """The successful execution payload embedded in a job status response."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    artifacts: list[dict[str, object]] = Field(default_factory=list)


class JobSubmitResponse(BaseModel):
    job_id: str
    state: JobState


class JobStatusResponse(BaseModel):
    job_id: str
    state: JobState
    created_at: str
    updated_at: str
    result_code: ResultCode | None = None
    error_code: ErrorCode | None = None
    detail: str | None = None
    result: SandboxResult | None = None


class JobCancelResponse(BaseModel):
    job_id: str
    state: JobState


class CapacityStatus(BaseModel):
    """Aggregate capacity report for ``GET /v1/capacity``."""

    max_concurrent: int
    in_use: int
    available: int
    active_jobs: int
    tracked_jobs: int


class ErrorResponse(BaseModel):
    error_code: ErrorCode
    detail: str
