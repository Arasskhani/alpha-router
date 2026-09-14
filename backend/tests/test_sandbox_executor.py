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


def test_executor_polls_job_to_success() -> None:
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

    result = asyncio.run(go())
    assert result["stdout"] == "ok\n"


def test_cancelling_executor_deletes_active_broker_job() -> None:
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

    async def go():
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

    asyncio.run(go())
