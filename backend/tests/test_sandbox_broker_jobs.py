"""Lifecycle tests for the additive sandbox broker job API."""

import asyncio
import base64
import contextlib
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import sandbox_broker as broker
from app.sandbox.contracts import JobState, JobSubmitRequest

TOKEN = "t" * 48


@contextlib.contextmanager
def _isolated(concurrency: int = 4):
    """Give each test its own job store, lock, and capacity semaphore.

    Fresh asyncio primitives are constructed per test so they bind to that
    test's event loop only (never reused across loops).
    """
    with (
        patch.object(broker, "_jobs", {}),
        patch.object(broker, "_jobs_lock", asyncio.Lock()),
        patch.object(broker, "_semaphore", asyncio.Semaphore(concurrency)),
    ):
        yield


def _body(response) -> dict:
    return json.loads(response.body)


class _FakeProc:
    def __init__(self) -> None:
        self.kills = 0

    def kill(self) -> None:
        self.kills += 1

    async def wait(self) -> int:
        return -9


async def test_submit_runs_job_and_reports_success() -> None:
    async def run():
        result = {"stdout": "hi", "stderr": "", "exit_code": 0, "artifacts": []}
        with patch.object(broker, "_run_container", AsyncMock(return_value=result)):
            resp = await broker.submit_job(JobSubmitRequest(code="print('hi')"))
            assert resp.status_code == 202
            job_id = _body(resp)["job_id"]
            await asyncio.wait_for(broker._jobs[job_id].task, 1)

            status = await broker.get_job(job_id)
            payload = _body(status)
            assert payload["state"] == "succeeded"
            assert payload["result_code"] == "ok"
            assert payload["error_code"] is None
            assert payload["result"]["stdout"] == "hi"
            # capacity slot released exactly once
            assert broker._semaphore._value == 4

    with _isolated():
        await run()


async def test_nonzero_exit_still_succeeds_with_result_code() -> None:
    async def run():
        result = {"stdout": "", "stderr": "boom", "exit_code": 3, "artifacts": []}
        with patch.object(broker, "_run_container", AsyncMock(return_value=result)):
            resp = await broker.submit_job(JobSubmitRequest(code="raise SystemExit(3)"))
            job_id = _body(resp)["job_id"]
            await asyncio.wait_for(broker._jobs[job_id].task, 1)
            payload = _body(await broker.get_job(job_id))
            assert payload["state"] == "succeeded"
            assert payload["result_code"] == "nonzero_exit"
            assert payload["result"]["exit_code"] == 3

    with _isolated():
        await run()


async def test_timeout_maps_to_terminal_timeout_state() -> None:
    async def run():
        exc = broker.HTTPException(status_code=504, detail="Sandbox execution timed out")
        with patch.object(broker, "_run_container", AsyncMock(side_effect=exc)):
            resp = await broker.submit_job(JobSubmitRequest(code="while True: pass"))
            job_id = _body(resp)["job_id"]
            await asyncio.wait_for(broker._jobs[job_id].task, 1)
            payload = _body(await broker.get_job(job_id))
            assert payload["state"] == "timeout"
            assert payload["error_code"] == "execution_timeout"
            assert payload["result"] is None
            assert broker._semaphore._value == 4

    with _isolated():
        await run()


async def test_submit_rejects_oversized_workspace_file_with_invalid_request() -> None:
    async def run():
        big = "x" * (broker.MAX_FILE_BYTES + 1)
        resp = await broker.submit_job(JobSubmitRequest(code="print(1)", files={"large.txt": big}))
        assert resp.status_code == 422
        assert _body(resp)["error_code"] == "invalid_request"
        assert broker._jobs == {}
        # No capacity consumed on rejection.
        assert broker._semaphore._value == 4

    with _isolated():
        await run()


async def test_submit_passes_files_b64_to_container_with_decoded_size_accounting() -> None:
    async def run():
        blob = bytes(range(256))
        encoded = base64.b64encode(blob).decode("ascii")
        result = {"stdout": "", "stderr": "", "exit_code": 0, "artifacts": []}
        # 256 decoded bytes fit under a 300-byte ceiling even though the
        # base64 string is 344 characters: accounting must be on decoded bytes.
        with (
            patch.object(broker, "MAX_FILE_BYTES", 300),
            patch.object(broker, "MAX_TOTAL_FILE_BYTES", 300),
            patch.object(broker, "_run_container", AsyncMock(return_value=result)) as run_container,
        ):
            resp = await broker.submit_job(
                JobSubmitRequest(code="print(1)", files={"a.txt": "hi"}, files_b64={"blob.bin": encoded})
            )
            assert resp.status_code == 202
            job_id = _body(resp)["job_id"]
            await asyncio.wait_for(broker._jobs[job_id].task, 1)
            assert _body(await broker.get_job(job_id))["state"] == "succeeded"
        request = run_container.await_args.args[0]
        assert isinstance(request, broker.ExecuteRequest)
        assert request.files_b64 == {"blob.bin": encoded}
        assert request.files == {"a.txt": "hi"}

    with _isolated():
        await run()


async def test_submit_rejects_combined_workspace_over_total_and_duplicates() -> None:
    async def run():
        with patch.object(broker, "MAX_TOTAL_FILE_BYTES", 100), patch.object(broker, "MAX_FILE_BYTES", 100):
            over_total = await broker.submit_job(
                JobSubmitRequest(
                    code="print(1)",
                    files={"t.txt": "x" * 60},
                    files_b64={"b.bin": base64.b64encode(b"y" * 60).decode("ascii")},
                )
            )
        duplicate = await broker.submit_job(
            JobSubmitRequest(code="print(1)", files={"same.bin": "x"}, files_b64={"same.bin": "AQID"})
        )
        bad_encoding = await broker.submit_job(JobSubmitRequest(code="print(1)", files_b64={"b.bin": "!!"}))
        for resp in (over_total, duplicate, bad_encoding):
            assert resp.status_code == 422
            assert _body(resp)["error_code"] == "invalid_request"
        assert broker._jobs == {}
        assert broker._semaphore._value == 4

    with _isolated():
        await run()


def test_jobs_endpoint_accepts_files_b64_over_http() -> None:
    result = {"stdout": "", "stderr": "", "exit_code": 0, "artifacts": []}
    with (
        _isolated(),
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "_run_container", AsyncMock(return_value=result)),
    ):
        response = TestClient(broker.app).post(
            "/v1/jobs",
            json={"code": "print(1)", "files_b64": {"a.bin": "AQID"}},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 202
    assert response.json()["state"] in {"pending", "running", "succeeded"}


async def test_no_capacity_returns_429_with_retry_after_and_error_code() -> None:
    async def run():
        resp = await broker.submit_job(JobSubmitRequest(code="print(1)"))
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == str(broker.RETRY_AFTER_SECONDS)
        assert _body(resp)["error_code"] == "capacity_unavailable"
        assert broker._jobs == {}

    with _isolated(concurrency=0):
        await run()


async def test_duplicate_job_id_conflicts() -> None:
    async def run():
        gate = asyncio.Event()
        started = asyncio.Event()

        async def fake_run(request, job=None):
            job.attach(_FakeProc(), "container-dup")
            started.set()
            await gate.wait()
            return {"stdout": "", "stderr": "", "exit_code": 0, "artifacts": []}

        with (
            patch.object(broker, "_run_container", fake_run),
            patch.object(broker, "_force_remove", AsyncMock()),
        ):
            first = await broker.submit_job(JobSubmitRequest(code="print(1)", job_id="dup"))
            assert first.status_code == 202
            await asyncio.wait_for(started.wait(), 1)

            second = await broker.submit_job(JobSubmitRequest(code="print(2)", job_id="dup"))
            assert second.status_code == 409
            assert _body(second)["error_code"] == "job_already_exists"

            gate.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(broker._jobs["dup"].task, 1)

    with _isolated():
        await run()


async def test_cancel_kills_container_releases_once_and_is_idempotent() -> None:
    async def run():
        gate = asyncio.Event()
        started = asyncio.Event()
        holder: dict[str, _FakeProc] = {}

        async def fake_run(request, job=None):
            proc = _FakeProc()
            holder["proc"] = proc
            job.attach(proc, "container-x")
            started.set()
            await gate.wait()
            return {"stdout": "", "stderr": "", "exit_code": 0, "artifacts": []}

        with (
            patch.object(broker, "_run_container", fake_run),
            patch.object(broker, "_force_remove", AsyncMock()) as force_remove,
        ):
            resp = await broker.submit_job(JobSubmitRequest(code="print(1)", job_id="abc"))
            assert resp.status_code == 202
            await asyncio.wait_for(started.wait(), 1)

            job = broker._jobs["abc"]
            assert job.state == JobState.RUNNING
            assert broker._semaphore._value == 3  # one slot held

            cancelled = await broker.cancel_job("abc")
            assert cancelled.status_code == 200
            assert _body(cancelled)["state"] == "cancelled"
            force_remove.assert_awaited_once_with("container-x")
            assert holder["proc"].kills == 1
            assert broker._semaphore._value == 4  # released exactly once

            # Idempotent: no extra kill/remove/release.
            again = await broker.cancel_job("abc")
            assert again.status_code == 200
            assert _body(again)["state"] == "cancelled"
            assert force_remove.await_count == 1
            assert holder["proc"].kills == 1
            assert broker._semaphore._value == 4

            gate.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(job.task, 1)
            # Late completion must not resurrect a terminal job.
            assert broker._jobs["abc"].state == JobState.CANCELLED
            assert broker._semaphore._value == 4

    with _isolated():
        await run()


async def test_unknown_job_returns_404_for_status_and_cancel() -> None:
    async def run():
        status = await broker.get_job("missing")
        assert status.status_code == 404
        assert _body(status)["error_code"] == "job_not_found"

        cancel = await broker.cancel_job("missing")
        assert cancel.status_code == 404
        assert _body(cancel)["error_code"] == "job_not_found"

    with _isolated():
        await run()


async def test_capacity_endpoint_reports_slots() -> None:
    async def run():
        with patch.object(broker, "MAX_CONCURRENT_SANDBOXES", 4):
            await broker._semaphore.acquire()  # simulate one in-flight execution
            report = await broker.capacity()
        assert report["max_concurrent"] == 4
        assert report["available"] == 3
        assert report["in_use"] == 1
        assert report["active_jobs"] == 0
        assert report["tracked_jobs"] == 0

    with _isolated():
        await run()


async def test_liveness_always_ok_and_readiness_gates_on_runtime() -> None:
    assert await broker.livez() == {"status": "alive"}
    with (
        patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}),
        patch.object(broker, "_runtime_ready", False),
        pytest.raises(broker.HTTPException) as exc,
    ):
        await broker.readyz()
    assert exc.value.status_code == 503
    assert "not ready" in str(exc.value.detail)


def test_job_endpoints_require_authentication() -> None:
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        client = TestClient(broker.app)
        assert client.post("/v1/jobs", json={"code": "print(1)"}).status_code == 401
        assert client.get("/v1/jobs/whatever").status_code == 401
        assert client.delete("/v1/jobs/whatever").status_code == 401


def test_capacity_endpoint_requires_authentication() -> None:
    with patch.dict(os.environ, {"SANDBOX_BROKER_TOKEN": TOKEN}):
        assert TestClient(broker.app).get("/v1/capacity").status_code == 401
