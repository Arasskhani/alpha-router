"""Two controls the product described but did not have.

**The off switch.** During an incident there was no way to stop Code
Interpreter. The lowest reachable ceiling is 1, which does not stop it - it
leaves one turn running and tells everyone else "busy, try again", which is not
what happened. Disabling refuses new turns with 503 and a code that says so,
while leases already held keep running to their end: killing work in flight is
a second incident.

**The execution timeout.** ``CODE_SANDBOX_TIMEOUT_SECONDS`` named a limit it
did not set. It shaped the client's polling deadline while the real kill sat at
a hardcoded 30 seconds inside the broker, so an operator who raised it saw no
change. The value now travels with the job and the broker clamps it to a
ceiling of its own.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import code_interpreter_capacity_service as caps
from tests.test_code_interpreter_capacity_service import _FakeRedis, _settings


def _run(coro):
    return asyncio.run(coro)


class TestTheOffSwitch:
    def test_a_new_turn_is_refused_with_503_and_a_code_that_names_the_reason(self):
        fake = _FakeRedis()

        async def go():
            with (
                patch.object(caps, "_redis_client", return_value=fake),
                patch.object(caps, "get_settings", return_value=_settings()),
            ):
                await fake.hset(caps._POLICY_HASH, mapping={"enabled": "0"})
                with pytest.raises(HTTPException) as excinfo:
                    await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
                assert excinfo.value.status_code == 503
                assert excinfo.value.detail["code"] == caps.CAPACITY_DISABLED_CODE
                # Not a 429: no Retry-After, because waiting does not help.
                assert "retry_after_seconds" not in excinfo.value.detail

        _run(go())

    def test_turns_already_running_are_left_alone(self):
        """Disabling stops admission, not execution. A half-finished analysis
        killed mid-flight is a second incident on top of the first."""
        fake = _FakeRedis()

        async def go():
            with (
                patch.object(caps, "_redis_client", return_value=fake),
                patch.object(caps, "get_settings", return_value=_settings()),
            ):
                permit = await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
                await fake.hset(caps._POLICY_HASH, mapping={"enabled": "0"})
                assert (await caps.code_interpreter_capacity_stats())["active"] == 1
                assert await caps.heartbeat_code_interpreter_turn(permit) is True
                assert await caps.release_code_interpreter_turn(permit) is True

        _run(go())

    def test_turning_it_back_on_admits_again(self):
        fake = _FakeRedis()

        async def go():
            with (
                patch.object(caps, "_redis_client", return_value=fake),
                patch.object(caps, "get_settings", return_value=_settings()),
            ):
                await fake.hset(caps._POLICY_HASH, mapping={"enabled": "0"})
                with pytest.raises(HTTPException):
                    await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
                await fake.hset(caps._POLICY_HASH, mapping={"enabled": "1"})
                assert await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))

        _run(go())

    def test_the_default_is_on_so_an_upgrade_changes_nothing(self):
        fake = _FakeRedis()

        async def go():
            with (
                patch.object(caps, "_redis_client", return_value=fake),
                patch.object(caps, "get_settings", return_value=_settings()),
            ):
                assert await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
                assert (await caps.code_interpreter_capacity_stats())["enabled"] is True

        _run(go())

    async def test_the_switch_survives_a_restart_because_it_lives_in_the_database(self, db_session):
        """Redis holds the published copy; the database holds the decision. A
        switch that a restart silently undoes is not a switch."""
        from app.services.code_interpreter_capacity_service import (
            get_code_interpreter_capacity_policy,
            set_code_interpreter_capacity_policy,
        )

        await set_code_interpreter_capacity_policy(db_session, enabled=False)
        assert (await get_code_interpreter_capacity_policy(db_session))["enabled"] == 0

    async def test_throwing_the_switch_does_not_disturb_the_ceilings(self, db_session):
        from app.services.code_interpreter_capacity_service import (
            get_code_interpreter_capacity_policy,
            set_code_interpreter_capacity_policy,
        )

        await set_code_interpreter_capacity_policy(db_session, global_max=17, per_subject_max=3, retry_after_seconds=45)
        await set_code_interpreter_capacity_policy(db_session, enabled=False)
        policy = await get_code_interpreter_capacity_policy(db_session)
        assert (policy["global_max"], policy["per_subject_max"], policy["retry_after_seconds"]) == (17, 3, 45)
        assert policy["enabled"] == 0


class TestTheExecutionTimeout:
    def test_the_requested_value_is_honoured(self):
        from app.sandbox_broker import _resolved_execution_timeout

        assert _resolved_execution_timeout(12) == 12

    def test_it_is_clamped_to_the_brokers_own_ceiling(self):
        """A client asking for an hour is exactly what the ceiling is for."""
        from app import sandbox_broker

        assert _clamped(sandbox_broker, 99_999) == sandbox_broker.HARD_MAX_EXECUTION_TIMEOUT_SECONDS

    def test_omitting_it_falls_back_to_the_brokers_default(self):
        from app import sandbox_broker

        assert _clamped(sandbox_broker, None) == sandbox_broker.EXECUTION_TIMEOUT_SECONDS

    def test_a_nonsensical_value_cannot_disable_the_timeout(self):
        from app.sandbox_broker import _resolved_execution_timeout

        assert _resolved_execution_timeout(0) == 1
        assert _resolved_execution_timeout(-5) == 1

    def test_the_client_sends_its_configured_timeout_with_the_job(self):
        """Without this on the wire, the setting only shaped the poll loop."""
        from app.sandbox.executor import DockerBrokerSandboxExecutor

        submitted: dict = {}

        class _Response:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.headers: dict[str, str] = {}

            def json(self):
                return self._payload

        class _Client:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                del args

            async def post(self, _url, *, json, headers):
                del headers
                submitted.update(json)
                return _Response(202, {"job_id": json["job_id"], "state": "pending"})

            async def get(self, _url, *, headers):
                del headers
                return _Response(
                    200,
                    {
                        "job_id": submitted["job_id"],
                        "state": "succeeded",
                        "created_at": "now",
                        "updated_at": "now",
                        "result": {"stdout": "", "stderr": "", "exit_code": 0, "artifacts": []},
                    },
                )

        async def go():
            executor = DockerBrokerSandboxExecutor(
                base_url="http://broker", token="t" * 32, execution_timeout_seconds=17
            )
            with patch("app.sandbox.executor.httpx.AsyncClient", _Client):
                await executor.execute("print(1)", {})

        _run(go())
        assert submitted["timeout_seconds"] == 17

    def test_the_submit_contract_accepts_and_bounds_it(self):
        from pydantic import ValidationError

        from app.sandbox.contracts import JobSubmitRequest

        assert JobSubmitRequest(code="x", timeout_seconds=30).timeout_seconds == 30
        assert JobSubmitRequest(code="x").timeout_seconds is None
        with pytest.raises(ValidationError):
            JobSubmitRequest(code="x", timeout_seconds=0)


def _clamped(module, requested):
    return module._resolved_execution_timeout(requested)


class TestTheSwitchSurvivesARedisFlush:
    """An off switch that turns itself back on when a cache is cleared is not an
    off switch — and clearing a cache is a normal thing to do during an
    incident, which is exactly when the switch is off.

    Redis holds the copy the admission path reads. Flushing it hands back an
    empty policy hash, and the permissive default behind that would admit turns
    again with nobody having decided to. The worker falls back to the last value
    it saw instead; a worker that has seen none is covered by the startup sync
    from the database.
    """

    def test_a_flushed_policy_hash_does_not_re_enable_it(self):
        fake = _FakeRedis()

        async def go():
            with (
                patch.object(caps, "_redis_client", return_value=fake),
                patch.object(caps, "get_settings", return_value=_settings()),
            ):
                await fake.hset(caps._POLICY_HASH, mapping={"enabled": "0"})
                with pytest.raises(HTTPException):
                    await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))

                fake.hashes.clear()  # FLUSHDB, or an evicted key

                with pytest.raises(HTTPException) as excinfo:
                    await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
                assert excinfo.value.detail["code"] == caps.CAPACITY_DISABLED_CODE

        _run(go())

    def test_a_flush_does_not_invent_a_disabled_state_either(self):
        """The fallback is the last value seen, not a blanket "assume off":
        a deployment that never touched the switch must keep working."""
        fake = _FakeRedis()

        async def go():
            with (
                patch.object(caps, "_redis_client", return_value=fake),
                patch.object(caps, "get_settings", return_value=_settings()),
            ):
                assert await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
                fake.hashes.clear()
                assert await caps.acquire_code_interpreter_turn(caps.subject_for_user(2))

        _run(go())

    async def test_publishing_the_policy_teaches_the_worker_the_value(self, db_session, monkeypatch):
        """``sync`` is what runs at startup; after it, a flush is survivable even
        by a worker that has served no request yet."""
        fake = _FakeRedis()
        monkeypatch.setattr(caps, "_redis_client", lambda: fake)
        caps.reset_capacity_policy_cache()

        await caps.set_code_interpreter_capacity_policy(db_session, enabled=False)
        await caps.sync_code_interpreter_capacity_policy(db_session)
        fake.hashes.clear()

        with pytest.raises(HTTPException) as excinfo:
            await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
        assert excinfo.value.detail["code"] == caps.CAPACITY_DISABLED_CODE
