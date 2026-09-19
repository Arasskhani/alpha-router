"""Every scheduler job body: it does its work through a committed session, and a
failure inside it is contained and logged rather than left to APScheduler.

Fourteen of the nineteen jobs had no test that so much as named them. They
run at 4am with nobody watching, which is exactly when "it raised and the
only trace is APScheduler's generic error line" is the worst outcome. Each
job is held to the same two properties here:

* the service it wraps is called with a session whose work is **committed**
  - a job that forgets to commit is a job that silently does nothing (the
  media purge had exactly that bug once);
* when the service raises, the job returns normally, rolls back, and logs
  through the scheduler logger with the traceback, so the failure has a name
  in the log rather than a stack trace with no context.

The services themselves have their own tests. These tests replace each
service with a fake that writes one row through the session it is handed, so
the commit is observable from a second session without seeding fourteen
domains.
"""

from __future__ import annotations

import datetime
import logging

import pytest
from sqlalchemy import select

from app.models.system import SystemSetting
from app.services import scheduler

MARK = "scheduler-job-test"


def _fake_service_writing_a_row(calls: list):
    """A stand-in service: records the call and writes a row with the session it got."""

    async def fake(db, *args, **kwargs):
        calls.append((args, kwargs))
        db.add(SystemSetting(key=f"{MARK}:{len(calls)}", value="written"))
        await db.flush()
        return {"rows_deleted": 1, "usage_events_cleared": 1, "video_jobs_cleared": 0, "retention_days": 1, "sent": 1}

    return fake


async def _rows_written(session_factory) -> int:
    async with session_factory() as db:
        rows = (await db.execute(select(SystemSetting).where(SystemSetting.key.like(f"{MARK}:%")))).scalars().all()
        return len(rows)


@pytest.fixture
def jobs_on_test_engine(session_factory, monkeypatch):
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)
    return session_factory


#: (job, where its service lives, the service's name)
_SESSION_JOBS = [
    (scheduler.job_reset_budgets, scheduler, "reset_all_monthly_budgets"),
    (scheduler.job_chat_stats_reconcile, "app.services.user_chat_storage_service", "reconcile_session_message_stats"),
    (scheduler.job_purge_deleted_projects, "app.services.project_service", "purge_expired_deleted_projects"),
    (scheduler.job_raw_payload_retention, "app.services.log_detail_retention_service", "purge_expired_raw_payloads"),
    (scheduler.job_tls_expiry_notice, "app.services.tls_expiry_service", "notify_expiring_certificates"),
    (scheduler.job_user_memory_maintenance, "app.services.memory_maintenance_service", "run_user_memory_maintenance"),
    (scheduler.job_system_metrics_snapshot, scheduler, "record_system_snapshot"),
    (scheduler.job_expire_budget_reservations, "app.services.budget_reservation_service", "expire_stale_reservations"),
]


def _target(where):
    if isinstance(where, str):
        import importlib

        return importlib.import_module(where)
    return where


def _quiet(monkeypatch, where, names):
    """Neutralise the job's other calls so the one under test is isolated."""

    async def nothing(*_a, **_k):
        return 0

    module = _target(where)
    for name in names:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, nothing)


@pytest.mark.parametrize(("job", "where", "name"), _SESSION_JOBS, ids=lambda x: getattr(x, "__name__", str(x)))
async def test_the_job_commits_the_work_its_service_does(jobs_on_test_engine, monkeypatch, job, where, name):
    calls: list = []
    monkeypatch.setattr(_target(where), name, _fake_service_writing_a_row(calls))
    _quiet(monkeypatch, scheduler, ["prune_old_snapshots"])
    _quiet(monkeypatch, "app.services.budget_reservation_service", ["reconcile_drifted_reserved_counters"])

    await job()

    assert calls, f"{job.__name__} never called {name}"
    assert await _rows_written(jobs_on_test_engine) == 1, f"{job.__name__} did not commit"


@pytest.mark.parametrize(("job", "where", "name"), _SESSION_JOBS, ids=lambda x: getattr(x, "__name__", str(x)))
async def test_a_failure_inside_the_job_is_contained_and_logged(
    jobs_on_test_engine, monkeypatch, caplog, job, where, name
):
    async def explode(*_a, **_k):
        raise RuntimeError("the service fell over")

    monkeypatch.setattr(_target(where), name, explode)
    _quiet(monkeypatch, scheduler, ["prune_old_snapshots"])

    with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
        await job()  # must not raise

    assert any(record.exc_info and "the service fell over" in str(record.exc_info[1]) for record in caplog.records), (
        f"{job.__name__} swallowed or leaked the failure without logging it"
    )


# --- jobs with logic of their own in the wrapper -------------------------------


async def test_model_sync_only_syncs_connections_that_are_due(jobs_on_test_engine, monkeypatch):
    from app.models.connection import Connection

    synced: list[str] = []

    async def fake_sync(db, connection, _key):
        synced.append(connection.name)

    monkeypatch.setattr(scheduler, "sync_connection_with_flash", fake_sync)
    monkeypatch.setattr(scheduler, "decrypt_secret", lambda _v: "key")
    now = datetime.datetime.utcnow()
    async with jobs_on_test_engine() as db:
        db.add_all(
            [
                Connection(
                    name="due",
                    provider_type="openai",
                    api_key_encrypted="x",
                    is_active=True,
                    sync_enabled=True,
                    sync_interval_hours=6,
                    last_sync_at=now - datetime.timedelta(hours=7),
                ),
                Connection(
                    name="fresh",
                    provider_type="openai",
                    api_key_encrypted="x",
                    is_active=True,
                    sync_enabled=True,
                    sync_interval_hours=6,
                    last_sync_at=now - datetime.timedelta(hours=1),
                ),
                Connection(
                    name="never",
                    provider_type="openai",
                    api_key_encrypted="x",
                    is_active=True,
                    sync_enabled=True,
                    sync_interval_hours=6,
                    last_sync_at=None,
                ),
                Connection(
                    name="off",
                    provider_type="openai",
                    api_key_encrypted="x",
                    is_active=True,
                    sync_enabled=False,
                    sync_interval_hours=6,
                    last_sync_at=None,
                ),
                Connection(
                    name="inactive",
                    provider_type="openai",
                    api_key_encrypted="x",
                    is_active=False,
                    sync_enabled=True,
                    sync_interval_hours=6,
                    last_sync_at=None,
                ),
            ]
        )
        await db.commit()

    await scheduler.job_sync_all_models()

    assert sorted(synced) == ["due", "never"]


async def test_model_sync_failure_on_one_connection_is_contained(jobs_on_test_engine, monkeypatch, caplog):
    """The first provider is down; the second must still be synced."""

    from app.models.connection import Connection

    synced: list[str] = []

    async def flaky(db, connection, _key):
        if connection.name == "broken":
            raise RuntimeError("provider down")
        synced.append(connection.name)

    monkeypatch.setattr(scheduler, "sync_connection_with_flash", flaky)
    monkeypatch.setattr(scheduler, "decrypt_secret", lambda _v: "key")
    async with jobs_on_test_engine() as db:
        db.add(
            Connection(name="broken", provider_type="openai", api_key_encrypted="x", is_active=True, sync_enabled=True)
        )
        db.add(
            Connection(name="healthy", provider_type="openai", api_key_encrypted="x", is_active=True, sync_enabled=True)
        )
        await db.commit()

    with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
        await scheduler.job_sync_all_models()

    assert synced == ["healthy"], "the broken provider stopped the others"
    assert any("provider down" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


async def test_user_media_cleanup_runs_only_for_users_whose_slot_has_passed(
    jobs_on_test_engine, monkeypatch, user, admin
):
    from app.models.user_media_prefs import UserMediaPreferences

    purged: list[int] = []

    async def fake_purge(db, user_id, days):
        purged.append(user_id)
        return 0

    monkeypatch.setattr(scheduler, "purge_user_media_older_than", fake_purge)
    monkeypatch.setattr(scheduler, "user_media_cleanup_due", lambda prefs, now, tz=None: prefs.user_id == user.id)
    async with jobs_on_test_engine() as db:
        db.add_all(
            [
                UserMediaPreferences(user_id=user.id, cleanup_enabled=True, cleanup_retention_days=30),
                UserMediaPreferences(user_id=admin.id, cleanup_enabled=True, cleanup_retention_days=30),
            ]
        )
        await db.commit()

    await scheduler.job_user_media_cleanup()

    assert purged == [user.id]
    async with jobs_on_test_engine() as db:
        served = await db.get(UserMediaPreferences, user.id)
        skipped = await db.get(UserMediaPreferences, admin.id)
        assert served.last_cleanup_at is not None, "the served user's slot is recorded (and committed)"
        assert skipped.last_cleanup_at is None


async def test_user_media_cleanup_failure_is_contained(jobs_on_test_engine, monkeypatch, caplog, user, admin):
    """The first user's purge fails; the second user is still served."""

    from app.models.user_media_prefs import UserMediaPreferences

    purged: list[int] = []

    async def flaky(db, user_id, days):
        if user_id == user.id:
            raise RuntimeError("bucket unreachable")
        purged.append(user_id)
        return 0

    monkeypatch.setattr(scheduler, "purge_user_media_older_than", flaky)
    monkeypatch.setattr(scheduler, "user_media_cleanup_due", lambda *_a, **_k: True)
    async with jobs_on_test_engine() as db:
        db.add(UserMediaPreferences(user_id=user.id, cleanup_enabled=True))
        db.add(UserMediaPreferences(user_id=admin.id, cleanup_enabled=True))
        await db.commit()

    with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
        await scheduler.job_user_media_cleanup()

    assert purged == [admin.id], "one user's failure stopped the rest"
    assert any("bucket unreachable" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)
    async with jobs_on_test_engine() as db:
        assert (await db.get(UserMediaPreferences, admin.id)).last_cleanup_at is not None


async def test_reclaim_stale_video_jobs_is_contained(monkeypatch, caplog):
    from app.services import video_job_service

    async def broken():
        raise RuntimeError("redis gone")

    monkeypatch.setattr(video_job_service, "reclaim_stale_video_jobs", broken)
    with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
        await scheduler.job_reclaim_stale_video_jobs()
    assert any("redis gone" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


async def test_refresh_dynamic_schedules_keeps_going_when_one_refresh_fails(monkeypatch, caplog):
    from app.services import auth_sync_scheduler

    order: list[str] = []

    async def first():
        order.append("storage")
        raise RuntimeError("storage schedule broken")

    async def second():
        order.append("chat")

    async def third():
        order.append("auth")

    monkeypatch.setattr(scheduler, "refresh_storage_cleanup_schedule", first)
    monkeypatch.setattr(scheduler, "refresh_chat_retention_cleanup_schedule", second)
    monkeypatch.setattr(auth_sync_scheduler, "refresh_auth_sync_schedules", third)

    with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
        await scheduler.job_refresh_dynamic_schedules()

    assert order == ["storage", "chat", "auth"], "one failing refresh must not stop the others"
    assert any("storage schedule broken" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


async def test_provider_cost_reconciliation_is_off_unless_enabled(monkeypatch):
    from app.services import provider_reconciliation_service as recon

    called = []
    monkeypatch.setattr(recon, "automatic_reconciliation_providers", lambda: called.append("listed") or [])
    settings = scheduler.get_settings()
    monkeypatch.setattr(settings, "cost_reconciliation_enabled", False)

    await scheduler.job_reconcile_provider_costs()

    assert called == [], "disabled means the job does not even ask which providers"


async def test_model_tool_compatibility_probes_each_claimed_model_and_prunes(jobs_on_test_engine, monkeypatch, caplog):
    from app.services import code_interpreter_probe_service as probe
    from app.services import model_tool_compatibility_service as compat

    probed: list = []
    pruned: list = []

    async def claim(db):
        # An integer, as the real claim returns: PostgreSQL rejects a string key.
        return [987_654]

    async def do_probe(db, model):
        probed.append(model.id)

    async def prune(db):
        pruned.append(True)

    monkeypatch.setattr(probe, "claim_due_probe_model_ids", claim)
    monkeypatch.setattr(probe, "probe_model_compatibility", do_probe)
    monkeypatch.setattr(compat, "prune_compatibility_events", prune)

    await scheduler.job_model_tool_compatibility()

    assert probed == [], "a claimed id with no model row is skipped, not probed"
    assert pruned == [True], "pruning still runs"
