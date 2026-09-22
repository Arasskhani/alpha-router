"""Tests for the portable, cancellable sandbox executor client."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.sandbox.executor import DockerBrokerSandboxExecutor


class _Response:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


async def test_executor_polls_job_to_success() -> None:
    class Client:
        polls = 0

        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, *args, **kwargs):
            del args, kwargs
            return _Response(202, {"job_id": "job-1", "state": "pending"})

        async def get(self, *args, **kwargs):
            del args, kwargs
            self.polls += 1
            if self.polls == 1:
                return _Response(
                    200,
                    {
                        "job_id": "job-1",
                        "state": "running",
                        "created_at": "now",
                        "updated_at": "now",
                    },
                )
            return _Response(
                200,
                {
                    "job_id": "job-1",
                    "state": "succeeded",
                    "created_at": "now",
                    "updated_at": "now",
                    "result": {
                        "stdout": "ok\n",
                        "stderr": "",
                        "exit_code": 0,
                        "artifacts": [],
                    },
                },
            )

    async def go():
        executor = DockerBrokerSandboxExecutor(
            base_url="http://broker",
            token="t" * 32,
            execution_timeout_seconds=20,
            poll_interval_seconds=0.05,
        )
        with patch("app.sandbox.executor.httpx.AsyncClient", Client):
            return await executor.execute("print(1)", {}, job_id="job-1")

    result = await go()
    assert result["stdout"] == "ok\n"


def _submit_capturing_client(posted: list[dict]):
    """A fake AsyncClient that records the submit JSON and reports instant success."""

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, url, *args, **kwargs):
            del args
            assert url.endswith("/v1/jobs")
            posted.append(kwargs["json"])
            return _Response(202, {"job_id": kwargs["json"]["job_id"], "state": "pending"})

        async def get(self, *args, **kwargs):
            del args, kwargs
            return _Response(
                200,
                {
                    "job_id": "job-b64",
                    "state": "succeeded",
                    "created_at": "now",
                    "updated_at": "now",
                    "result": {"stdout": "", "stderr": "", "exit_code": 0, "artifacts": []},
                },
            )

    return Client


def _executor() -> DockerBrokerSandboxExecutor:
    return DockerBrokerSandboxExecutor(base_url="http://broker", token="t" * 32, execution_timeout_seconds=20)


async def test_executor_sends_files_b64_in_submit_json() -> None:
    posted: list[dict] = []
    with patch("app.sandbox.executor.httpx.AsyncClient", _submit_capturing_client(posted)):
        await _executor().execute("print(1)", {"a.txt": "hi"}, files_b64={"blob.bin": "AQID"}, job_id="job-b64")
    assert len(posted) == 1
    assert posted[0]["files_b64"] == {"blob.bin": "AQID"}
    assert posted[0]["files"] == {"a.txt": "hi"}
    assert set(posted[0]) == {"job_id", "code", "files", "files_b64", "timeout_seconds"}


@pytest.mark.parametrize("files_b64", [None, {}])
async def test_executor_omits_files_b64_key_when_there_are_no_binaries(files_b64) -> None:
    posted: list[dict] = []
    with patch("app.sandbox.executor.httpx.AsyncClient", _submit_capturing_client(posted)):
        if files_b64 is None:
            await _executor().execute("print(1)", {"a.txt": "hi"}, job_id="job-b64")
        else:
            await _executor().execute("print(1)", {"a.txt": "hi"}, files_b64=files_b64, job_id="job-b64")
    assert posted == [{"job_id": "job-b64", "code": "print(1)", "files": {"a.txt": "hi"}, "timeout_seconds": 20}]
    assert "files_b64" not in posted[0]


async def test_cancelling_executor_deletes_active_broker_job() -> None:
    get_started = asyncio.Event()
    delete_called = asyncio.Event()

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, *args, **kwargs):
            del args, kwargs
            return _Response(202, {"job_id": "job-cancel", "state": "pending"})

        async def get(self, *args, **kwargs):
            del args, kwargs
            get_started.set()
            await asyncio.sleep(3600)

        async def delete(self, url, *args, **kwargs):
            del args, kwargs
            assert url.endswith("/v1/jobs/job-cancel")
            delete_called.set()
            return _Response(200, {"job_id": "job-cancel", "state": "cancelled"})

    executor = DockerBrokerSandboxExecutor(
        base_url="http://broker",
        token="t" * 32,
        execution_timeout_seconds=20,
    )
    with patch("app.sandbox.executor.httpx.AsyncClient", Client):
        task = asyncio.create_task(executor.execute("print(1)", {}, job_id="job-cancel"))
        await get_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert delete_called.is_set()
