"""Boot smoke-test regressions: app loggers at INFO, idempotent scheduler stop.

Both came out of running the real two-worker uvicorn boot: the leader line
was logged at INFO under a WARNING root and never appeared, and every worker
exit raised SchedulerNotRunningError because the leader's release callback
and the lifespan both stopped the scheduler in the same tick.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from app.branding import LOGGER_NAMESPACE
from app.services import scheduler as sched
from app.services.observability import configure_app_log_level


def test_configure_app_log_level_touches_only_app_loggers():
    root = logging.getLogger()
    previous_root = root.level
    try:
        root.setLevel(logging.WARNING)
        configure_app_log_level("debug")
        assert logging.getLogger(LOGGER_NAMESPACE).level == logging.DEBUG
        assert logging.getLogger("app").level == logging.DEBUG
        assert root.level == logging.WARNING
        configure_app_log_level("not-a-level")
        assert logging.getLogger("app").level == logging.INFO
    finally:
        root.setLevel(previous_root)
        configure_app_log_level("INFO")


def test_stop_scheduler_is_idempotent():
    with (
        patch.object(sched, "_shutdown_requested", False),
        patch.object(type(sched.scheduler), "running", property(lambda self: True)),
        patch.object(sched.scheduler, "shutdown") as shutdown,
    ):
        sched.stop_scheduler()
        sched.stop_scheduler()
        assert shutdown.call_count == 1
