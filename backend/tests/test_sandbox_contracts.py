"""Contract tests for the sandbox broker job wire models and state machine."""

import pytest
from pydantic import ValidationError

from app.sandbox.contracts import (
    ErrorCode,
    JobState,
    JobSubmitRequest,
    ResultCode,
    can_transition,
    is_terminal,
)


def test_terminal_states_are_exactly_the_settled_outcomes() -> None:
    assert is_terminal(JobState.SUCCEEDED)
    assert is_terminal(JobState.FAILED)
    assert is_terminal(JobState.CANCELLED)
    assert is_terminal(JobState.TIMEOUT)
    assert not is_terminal(JobState.PENDING)
    assert not is_terminal(JobState.RUNNING)


def test_state_machine_allows_only_forward_transitions() -> None:
    assert can_transition(JobState.PENDING, JobState.RUNNING)
    assert can_transition(JobState.PENDING, JobState.CANCELLED)
    assert can_transition(JobState.RUNNING, JobState.SUCCEEDED)
    assert can_transition(JobState.RUNNING, JobState.FAILED)
    assert can_transition(JobState.RUNNING, JobState.TIMEOUT)
    assert can_transition(JobState.RUNNING, JobState.CANCELLED)

    # Terminal states never transition again.
    for terminal in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.TIMEOUT):
        for target in JobState:
            assert not can_transition(terminal, target)

    # No backward edges.
    assert not can_transition(JobState.RUNNING, JobState.PENDING)


def test_error_and_result_codes_are_stable_strings() -> None:
    assert ErrorCode.CAPACITY_UNAVAILABLE.value == "capacity_unavailable"
    assert ErrorCode.EXECUTION_TIMEOUT.value == "execution_timeout"
    assert ErrorCode.OUTPUT_LIMIT_EXCEEDED.value == "output_limit_exceeded"
    assert ErrorCode.SANDBOX_UNAVAILABLE.value == "sandbox_unavailable"
    assert ErrorCode.INVALID_SANDBOX_RESPONSE.value == "invalid_sandbox_response"
    assert ErrorCode.EXECUTION_FAILED.value == "execution_failed"
    assert ErrorCode.CANCELLED.value == "cancelled"
    assert ErrorCode.JOB_NOT_FOUND.value == "job_not_found"
    assert ErrorCode.JOB_ALREADY_EXISTS.value == "job_already_exists"
    assert ErrorCode.INVALID_REQUEST.value == "invalid_request"
    assert ErrorCode.NOT_AUTHORIZED.value == "not_authorized"
    assert ErrorCode.REQUEST_TOO_LARGE.value == "request_too_large"
    assert ResultCode.OK.value == "ok"
    assert ResultCode.NONZERO_EXIT.value == "nonzero_exit"


def test_submit_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JobSubmitRequest(code="print(1)", image="attacker-controlled")


def test_submit_request_validates_optional_job_id() -> None:
    assert JobSubmitRequest(code="print(1)").job_id is None
    assert JobSubmitRequest(code="print(1)", job_id="Job_1.2-3").job_id == "Job_1.2-3"
    for bad in ["../etc", "a/b", "a b", ".", ""]:
        with pytest.raises(ValidationError):
            JobSubmitRequest(code="print(1)", job_id=bad)


def test_submit_request_requires_nonempty_code() -> None:
    with pytest.raises(ValidationError):
        JobSubmitRequest(code="")
