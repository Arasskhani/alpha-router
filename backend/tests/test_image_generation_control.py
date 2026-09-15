"""Deadline and disconnect controls for long-running image generation."""

import asyncio

import pytest

from app.api.images import ImageClientDisconnected, _await_image_work


class _RequestStub:
    def __init__(self, disconnected: bool = False):
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def test_image_work_returns_result_before_deadline():
    async def _run():
        async def work():
            await asyncio.sleep(0)
            return "ok"

        return await _await_image_work(
            work(),
            request=_RequestStub(),
            timeout_seconds=1,
        )

    assert await _run() == "ok"


async def test_image_work_enforces_hard_deadline():
    async def work():
        await asyncio.sleep(1)

    with pytest.raises(asyncio.TimeoutError):
        await _await_image_work(
            work(),
            request=_RequestStub(),
            timeout_seconds=0.01,
        )


async def test_image_work_cancels_when_client_disconnects():
    async def work():
        await asyncio.sleep(1)

    with pytest.raises(ImageClientDisconnected):
        await _await_image_work(
            work(),
            request=_RequestStub(disconnected=True),
            timeout_seconds=1,
        )
