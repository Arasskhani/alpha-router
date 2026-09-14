"""Execution backend abstraction for cancellable Code Interpreter jobs."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.sandbox.contracts import JobState


@dataclass(frozen=True)
class SandboxExecutorError(Exception):
    status_code: int
    detail: str
    error_code: str | None = None
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.detail


class SandboxJobCancelled(Exception):
    """The submitted job reached the broker's cancelled terminal state."""


class SandboxExecutor(Protocol):
    async def execute(
        self,
        code: str,
        files: dict[str, str],
        *,
        job_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def cancel(self, job_id: str) -> bool: ...

    async def capacity(self) -> dict[str, Any]: ...


class DockerBrokerSandboxExecutor:
    """Current Docker implementation behind the portable executor contract."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        execution_timeout_seconds: int,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.execution_timeout_seconds = max(1, int(execution_timeout_seconds))
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _error_from_response(response: httpx.Response) -> SandboxExecutorError:
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = {}
        detail = str(payload.get("detail") or f"Sandbox broker HTTP {response.status_code}")
        retry_value = response.headers.get("Retry-After")
        try:
            retry_after = int(retry_value) if retry_value else None
        except (TypeError, ValueError):
            retry_after = None
        return SandboxExecutorError(
            status_code=response.status_code,
            detail=detail[:500],
            error_code=(str(payload.get("error_code")) if payload.get("error_code") is not None else None),
            retry_after_seconds=retry_after,
        )

    async def execute(
        self,
        code: str,
        files: dict[str, str],
        *,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_job_id = job_id or uuid.uuid4().hex
        timeout = httpx.Timeout(max(self.execution_timeout_seconds + 20, 45))
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            submit = await client.post(
                f"{self.base_url}/v1/jobs",
                json={
                    "job_id": resolved_job_id,
                    "code": code,
                    "files": files,
                },
                headers=self._headers,
            )
            if submit.status_code != 202:
                raise self._error_from_response(submit)

            deadline = time.monotonic() + self.execution_timeout_seconds + 20
            try:
                while True:
                    status_response = await client.get(
                        f"{self.base_url}/v1/jobs/{resolved_job_id}",
                        headers=self._headers,
                    )
                    if status_response.status_code != 200:
                        raise self._error_from_response(status_response)
                    payload = status_response.json()
                    state = JobState(str(payload.get("state")))
                    if state == JobState.SUCCEEDED:
                        result = payload.get("result")
                        if not isinstance(result, dict):
                            raise SandboxExecutorError(
                                502,
                                "Sandbox broker returned no execution result",
                                "invalid_sandbox_response",
                            )
                        return result
                    if state == JobState.CANCELLED:
                        raise SandboxJobCancelled(resolved_job_id)
                    if state in {JobState.FAILED, JobState.TIMEOUT}:
                        raise SandboxExecutorError(
                            504 if state == JobState.TIMEOUT else 502,
                            str(payload.get("detail") or f"Sandbox job {state.value}"),
                            (str(payload.get("error_code")) if payload.get("error_code") is not None else None),
                        )
                    if time.monotonic() >= deadline:
                        cancel_task = asyncio.create_task(self._cancel_with_client(client, resolved_job_id))
                        await asyncio.shield(cancel_task)
                        raise SandboxExecutorError(
                            504,
                            "Sandbox job polling timed out",
                            "execution_timeout",
                        )
                    await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                cancel_task = asyncio.create_task(self._cancel_with_client(client, resolved_job_id))
                try:
                    await asyncio.shield(cancel_task)
                except Exception:
                    pass
                raise

    async def _cancel_with_client(
        self,
        client: httpx.AsyncClient,
        job_id: str,
    ) -> bool:
        response = await client.delete(
            f"{self.base_url}/v1/jobs/{job_id}",
            headers=self._headers,
        )
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise self._error_from_response(response)
        return True

    async def cancel(self, job_id: str) -> bool:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10),
            trust_env=False,
        ) as client:
            return await self._cancel_with_client(client, job_id)

    async def capacity(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10),
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{self.base_url}/v1/capacity",
                headers=self._headers,
            )
            if response.status_code != 200:
                raise self._error_from_response(response)
            payload = response.json()
            if not isinstance(payload, dict):
                raise SandboxExecutorError(
                    502,
                    "Sandbox broker returned invalid capacity data",
                    "invalid_sandbox_response",
                )
            return payload
