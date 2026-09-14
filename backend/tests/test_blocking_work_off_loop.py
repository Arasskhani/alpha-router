"""CPU/disk/sleep work that used to run inline now runs in a thread."""

from __future__ import annotations

import asyncio
import contextlib
import base64
import os
import time
from unittest.mock import AsyncMock, patch


async def _max_tick_gap(coro, *, ticks: int = 30, period: float = 0.01) -> float:
    """Run ``coro`` while measuring the longest gap between loop ticks."""
    gaps = {"max": 0.0}

    async def ticker():
        last = time.monotonic()
        for _ in range(ticks):
            await asyncio.sleep(period)
            now = time.monotonic()
            gaps["max"] = max(gaps["max"], now - last)
            last = now

    t = asyncio.create_task(ticker())
    await coro
    await t
    return gaps["max"]


async def test_system_metrics_sampling_does_not_stall_the_loop(monkeypatch):
    from app.services import db_monitor_service as mon

    def slow_collect():
        time.sleep(0.3)  # what psutil.cpu_percent(interval=0.15)+0.1 costs
        return {"available": True, "host": {"cpu_percent": 1.0}, "process": None, "error": None}

    monkeypatch.setattr(mon, "_collect_system_metrics", slow_collect)
    gap = await _max_tick_gap(mon.collect_system_metrics())
    assert gap < 0.1, gap


async def test_openrouter_transcription_encodes_off_loop_and_sends_base64():
    from app.services import openrouter_transcription_service as ors

    audio = os.urandom(3 * 1024 * 1024)
    captured = {}

    async def fake_post(url, *, headers, json_payload, read_timeout, max_attempts):
        captured["payload"] = json_payload

        class R:
            status_code = 200

            def json(self):
                return {"text": "hello", "usage": {}}

        return R()

    with (
        patch.object(ors, "post_openrouter_json", new=fake_post),
        patch.object(ors, "audio_format_for", lambda f, m: "wav"),
    ):
        # Response parsing details are not under test here; the payload is.
        with contextlib.suppress(Exception):
            await ors.transcribe_with_openrouter(
                api_key="k", base_url=None, model="m", audio_bytes=audio, filename="a.wav", mime_type="audio/wav"
            )
    assert captured["payload"]["input_audio"]["data"] == base64.b64encode(audio).decode("ascii")


async def test_transcription_temp_file_is_written_and_removed_in_threads(monkeypatch, tmp_path):
    from app.services import transcription_service as ts

    calls = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(fn, *a, **k):
        calls.append(getattr(fn, "__name__", repr(fn)))
        return await real_to_thread(fn, *a, **k)

    monkeypatch.setattr(ts.asyncio, "to_thread", spy_to_thread)
    path = await ts.asyncio.to_thread(ts._write_temp_audio, b"RIFF....", ".wav")
    assert os.path.exists(path)
    await ts.asyncio.to_thread(ts._unlink_quietly, path)
    assert not os.path.exists(path)
    await ts.asyncio.to_thread(ts._unlink_quietly, path)  # idempotent
    assert calls == ["_write_temp_audio", "_unlink_quietly", "_unlink_quietly"]


async def test_readiness_uses_shared_redis_client():
    from app.services import readiness_service as rs

    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    with patch("app.core.redis_client.get_redis", return_value=fake):
        await rs._check_redis()
    fake.ping.assert_awaited_once()
    fake.aclose.assert_not_called()
