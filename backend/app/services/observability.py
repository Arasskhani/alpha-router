"""Bounded Prometheus metrics, OpenTelemetry tracing, and safe JSON logs."""

from __future__ import annotations

import contextlib
import contextvars
import datetime
import json
import logging
import os
import re
import time
import uuid
from collections import Counter
from threading import Lock
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client import Counter as PrometheusCounter

from app.branding import LOGGER_NAMESPACE
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_KNOWN_EVENTS = frozenset(
    {
        "redis_fallback",
        "broker_failure",
        "ssrf_block",
        "csrf_failure",
        "repeated_401",
        "budget_hold_leak",
        "budget_reserved_drift_repaired",
        "code_interpreter_capacity_rejected",
        "code_interpreter_disabled_rejected",
        "code_interpreter_lease_expired",
        "code_interpreter_cancelled",
        "docs_denied",
        "production_guard_warning",
        "sandbox_orphan_removed",
        "video_job_started",
        "video_provider_submit",
        # Could not reach the provider at all (handshake refused, black-holed
        # or timed out). Watch the rate: it is normally zero, and a sustained
        # non-zero value means this host's egress is losing new connections --
        # the condition that used to surface only as unexplained video
        # failures, and that no amount of application retrying truly fixes.
        "upstream_connect_failure",
        # A video status GET failed and was retried. One is noise; a steady
        # stream is the same egress problem seen from the job side.
        "video_poll_retry",
        "video_job_completed",
        "video_job_failed",
        "agent_run_failed",
        "agent_run_blocked",
        "agent_retrieval_unavailable",
        "evaluation_gate_failed",
        "evaluation_gate_passed",
        "knowledge_job_dead",
        "retention_purge_blocked",
        "memory_extract_failed",
        "memory_retrieval_fallback",
        "admin_ip_denied",
        "tls_expiry_notice",
    }
)
_lock = Lock()
_counts: Counter[str] = Counter()
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "alpharouter_correlation_id",
    default="",
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
_AGENT_STATUSES = frozenset(
    {
        "route_required",
        "abstained",
        "succeeded",
        "blocked",
        "failed",
        "cancelled",
    }
)
_ROUTING_OUTCOMES = frozenset(
    {
        "explicit",
        "selected",
        "no_match",
        "clarification",
        "handoff",
        "route_required",
        "none",
    }
)
_RETRIEVAL_OUTCOMES = frozenset(
    {
        "not_attempted",
        "disabled",
        "private_mode_disabled",
        "succeeded",
        "empty",
        "abstained",
        "failed",
        "unavailable",
    }
)
_EVALUATION_STATUSES = frozenset({"awaiting_review", "passed", "failed", "error", "cancelled"})
_DEPENDENCIES = frozenset({"postgres", "redis", "qdrant", "seaweedfs", "clamav", "provider"})
_MULTIPROCESS = bool(os.getenv("PROMETHEUS_MULTIPROC_DIR"))
_registry = None if _MULTIPROCESS else CollectorRegistry(auto_describe=True)
_metric_kwargs = {} if _registry is None else {"registry": _registry}

_EVENT_TOTAL = PrometheusCounter(
    "alpharouter_events_total",
    "Bounded Alpharouter security and operations events.",
    ("event",),
    **_metric_kwargs,
)
_HTTP_REQUESTS = PrometheusCounter(
    "alpharouter_http_requests_total",
    "HTTP requests by bounded method, route template, and status class.",
    ("method", "route", "status_class"),
    **_metric_kwargs,
)
_HTTP_DURATION = Histogram(
    "alpharouter_http_request_duration_seconds",
    "HTTP request duration by bounded method and route template.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120),
    **_metric_kwargs,
)
_HTTP_INFLIGHT = Gauge(
    "alpharouter_http_requests_inflight",
    "Current in-flight HTTP requests in this process.",
    multiprocess_mode="livesum",
    **_metric_kwargs,
)
_AGENT_RUNS = PrometheusCounter(
    "alpharouter_agent_runs_total",
    "Terminal Agent runs without user, model, or Agent identifiers.",
    ("status", "routing_outcome", "retrieval_outcome", "private_mode"),
    **_metric_kwargs,
)
_AGENT_LATENCY = Histogram(
    "alpharouter_agent_run_duration_seconds",
    "Terminal Agent run duration by bounded outcome.",
    ("status", "private_mode"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    **_metric_kwargs,
)
_AGENT_COST = PrometheusCounter(
    "alpharouter_agent_cost_usd_total",
    "Accumulated Agent run cost by bounded outcome.",
    ("status", "private_mode"),
    **_metric_kwargs,
)
_EVALUATION_RUNS = PrometheusCounter(
    "alpharouter_evaluation_runs_total",
    "Evaluation runs by bounded terminal status and trigger.",
    ("status", "trigger"),
    **_metric_kwargs,
)
_MEMORY_EXTRACT_JOBS = PrometheusCounter(
    "alpharouter_memory_extract_jobs_total",
    "Automatic memory extraction jobs by bounded outcome.",
    ("outcome", "scope"),
    **_metric_kwargs,
)
_MEMORY_EXTRACT_DURATION = Histogram(
    "alpharouter_memory_extract_duration_seconds",
    "Automatic memory extraction duration.",
    ("scope",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    **_metric_kwargs,
)
_MEMORY_ITEMS = PrometheusCounter(
    "alpharouter_memory_items_total",
    "Memory consolidation operations by bounded op.",
    ("op", "scope"),
    **_metric_kwargs,
)
_MEMORY_RETRIEVAL_DURATION = Histogram(
    "alpharouter_memory_retrieval_duration_seconds",
    "Memory retrieval duration.",
    ("scope",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    **_metric_kwargs,
)
_MEMORY_RETRIEVAL_FALLBACK = PrometheusCounter(
    "alpharouter_memory_retrieval_fallback_total",
    "Memory retrieval fallbacks by bounded reason.",
    ("reason", "scope"),
    **_metric_kwargs,
)
_MEMORY_INJECTED = Histogram(
    "alpharouter_memory_injected_items",
    "Number of memory facts injected into a chat turn.",
    ("scope",),
    buckets=(0, 1, 2, 4, 6, 8, 12, 20, 30),
    **_metric_kwargs,
)
_MEMORY_EMBEDDING_BACKLOG = Gauge(
    "alpharouter_memory_embedding_backlog",
    "Pending or failed memory embeddings awaiting index.",
    multiprocess_mode="livemostrecent",
    **_metric_kwargs,
)
_BUDGET_RESERVED_DRIFT = Gauge(
    "alpharouter_budget_reserved_drift_usd",
    "USD by which reserved counters exceeded their open holds at the last reconciliation run.",
    multiprocess_mode="livemostrecent",
    **_metric_kwargs,
)
_DEPENDENCY_READY = Gauge(
    "alpharouter_dependency_ready",
    "Dependency readiness (1 ready, 0 unavailable).",
    ("component",),
    multiprocess_mode="livemostrecent",
    **_metric_kwargs,
)
_tracer_provider: TracerProvider | None = None
_tracer = trace.get_tracer("alpharouter")


def increment(event: str) -> None:
    """Increment a known event without accepting user-controlled labels."""
    if event not in _KNOWN_EVENTS:
        return
    with _lock:
        _counts[event] += 1
    _EVENT_TOTAL.labels(event=event).inc()


def snapshot() -> dict[str, int]:
    """Return all known counters, including events still at zero."""
    with _lock:
        return {event: int(_counts.get(event, 0)) for event in sorted(_KNOWN_EVENTS)}


def reset() -> None:
    """Test hook to reset process counters."""
    with _lock:
        _counts.clear()
    if not _MULTIPROCESS:
        for metric in (
            _EVENT_TOTAL,
            _HTTP_REQUESTS,
            _HTTP_DURATION,
            _AGENT_RUNS,
            _AGENT_LATENCY,
            _AGENT_COST,
            _EVALUATION_RUNS,
            _DEPENDENCY_READY,
        ):
            metric.clear()
        _HTTP_INFLIGHT.set(0)


def _bounded_label(value: str, allowed: frozenset[str]) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in allowed else "other"


def record_agent_run(
    *,
    status: str,
    routing_outcome: str,
    retrieval_outcome: str,
    private_mode: bool,
    latency_ms: int | None,
    cost_usd: float,
) -> None:
    """Record one Agent terminal outcome with no high-cardinality labels."""

    status_label = _bounded_label(status, _AGENT_STATUSES)
    routing_label = _bounded_label(routing_outcome, _ROUTING_OUTCOMES)
    retrieval_label = _bounded_label(retrieval_outcome, _RETRIEVAL_OUTCOMES)
    private_label = "true" if private_mode else "false"
    _AGENT_RUNS.labels(
        status=status_label,
        routing_outcome=routing_label,
        retrieval_outcome=retrieval_label,
        private_mode=private_label,
    ).inc()
    if latency_ms is not None:
        _AGENT_LATENCY.labels(
            status=status_label,
            private_mode=private_label,
        ).observe(max(0, latency_ms) / 1000)
    _AGENT_COST.labels(
        status=status_label,
        private_mode=private_label,
    ).inc(max(0.0, float(cost_usd or 0)))
    if status_label in {"failed", "blocked"}:
        increment(f"agent_run_{status_label}")
    if retrieval_label == "unavailable":
        increment("agent_retrieval_unavailable")


def record_evaluation_run(*, status: str, trigger: str) -> None:
    status_label = _bounded_label(status, _EVALUATION_STATUSES)
    trigger_label = _bounded_label(
        trigger,
        frozenset({"manual", "publish_gate", "ci", "seed", "scheduled"}),
    )
    _EVALUATION_RUNS.labels(status=status_label, trigger=trigger_label).inc()
    if status_label == "passed":
        increment("evaluation_gate_passed")
    elif status_label in {"failed", "error"}:
        increment("evaluation_gate_failed")


_MEMORY_EXTRACT_OUTCOMES = frozenset({"succeeded", "failed", "skipped", "dead", "retry", "duplicate"})
_MEMORY_ITEM_OPS = frozenset({"add", "update", "supersede", "evict", "suppress-hit", "reject"})
_MEMORY_FALLBACK_REASONS = frozenset({"timeout_or_error", "unavailable", "unconfigured"})
_MEMORY_SCOPES = frozenset({"user", "project"})


def observe_memory_extract_job(*, outcome: str, duration_seconds: float | None = None, scope: str = "user") -> None:
    label = _bounded_label(outcome, _MEMORY_EXTRACT_OUTCOMES)
    scope_label = _bounded_label(scope, _MEMORY_SCOPES)
    _MEMORY_EXTRACT_JOBS.labels(outcome=label, scope=scope_label).inc()
    if duration_seconds is not None:
        _MEMORY_EXTRACT_DURATION.labels(scope=scope_label).observe(max(0.0, float(duration_seconds)))
    if label == "failed":
        increment("memory_extract_failed")


def observe_memory_item(op: str, *, scope: str = "user") -> None:
    _MEMORY_ITEMS.labels(
        op=_bounded_label(op, _MEMORY_ITEM_OPS),
        scope=_bounded_label(scope, _MEMORY_SCOPES),
    ).inc()


def observe_memory_retrieval(*, duration_seconds: float, injected: int, scope: str = "user") -> None:
    scope_label = _bounded_label(scope, _MEMORY_SCOPES)
    _MEMORY_RETRIEVAL_DURATION.labels(scope=scope_label).observe(max(0.0, float(duration_seconds)))
    _MEMORY_INJECTED.labels(scope=scope_label).observe(max(0, int(injected)))


def observe_memory_retrieval_fallback(reason: str, *, scope: str = "user") -> None:
    _MEMORY_RETRIEVAL_FALLBACK.labels(
        reason=_bounded_label(reason, _MEMORY_FALLBACK_REASONS),
        scope=_bounded_label(scope, _MEMORY_SCOPES),
    ).inc()
    increment("memory_retrieval_fallback")


def set_memory_embedding_backlog(count: int) -> None:
    _MEMORY_EMBEDDING_BACKLOG.set(max(0, int(count)))


def observe_budget_reserved_drift(total_usd: float) -> None:
    """Record the drift the reconciliation job found (0 when counters were exact).

    Phase 4.2 moved the counters to NUMERIC; once this stays at zero for a
    month the repair job can be retired (plan step 4.2).
    """
    _BUDGET_RESERVED_DRIFT.set(max(0.0, float(total_usd or 0.0)))


def set_dependency_ready(component: str, ready: bool) -> None:
    clean = str(component or "").strip().lower()
    if clean not in _DEPENDENCIES:
        return
    _DEPENDENCY_READY.labels(component=clean).set(1 if ready else 0)


def prometheus_payload() -> tuple[bytes, str]:
    if _MULTIPROCESS:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    assert _registry is not None
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def correlation_id() -> str:
    return _correlation_id.get()


@contextlib.contextmanager
def correlation_scope(value: str):
    """Stamp background work with an id, the way the HTTP middleware does.

    A worker runs outside any request, so its log lines carried no correlation
    id and nothing tied them to the row it wrote. Using the job's own id makes
    `grep <id>` in the container log and the API Logs row the same thing.
    """
    token = _correlation_id.set(value)
    try:
        yield value
    finally:
        _correlation_id.reset(token)


class JsonLogFormatter(logging.Formatter):
    """Stable JSON formatter that excludes arbitrary record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span().get_span_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name[:160],
            "message": record.getMessage(),
        }
        current_correlation = correlation_id()
        if current_correlation:
            payload["correlation_id"] = current_correlation
        if span.is_valid:
            payload["trace_id"] = format(span.trace_id, "032x")
            payload["span_id"] = format(span.span_id, "016x")
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)[:8_000]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_app_log_level(level_name: str) -> None:
    """Make the application's own INFO lines visible.

    The root logger stays at WARNING (third-party noise), but every logger the
    app writes to - the ``alpha_router`` namespace and the ``app.*`` module
    loggers - gets APP_LOG_LEVEL (INFO by default). Under uvicorn nothing set
    these before, so operational lines such as "This worker is now the
    scheduler leader" or "LDAP sync: prune suppressed" were silently dropped.
    """
    level = getattr(logging, str(level_name or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for name in (LOGGER_NAMESPACE, "app"):
        logging.getLogger(name).setLevel(level)


def configure_json_logging(enabled: bool) -> None:
    if not enabled:
        return
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    formatter = JsonLogFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)


def configure_telemetry(
    *,
    enabled: bool,
    service_name: str,
    endpoint: str,
    sample_ratio: float,
) -> None:
    """Configure a bounded OTLP tracer once per process."""

    global _tracer, _tracer_provider
    if not enabled or _tracer_provider is not None:
        return
    if not endpoint.strip():
        raise RuntimeError("OTEL_EXPORTER_OTLP_ENDPOINT is required when tracing is enabled")
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": str(service_name or "alpharouter")[:128],
                "service.version": "1.0.0",
            }
        ),
        sampler=TraceIdRatioBased(max(0.0, min(float(sample_ratio), 1.0))),
    )
    exporter = OTLPSpanExporter(endpoint=endpoint.strip())
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    _tracer = provider.get_tracer("alpharouter")


def shutdown_telemetry() -> None:
    if _tracer_provider is not None:
        _tracer_provider.force_flush(timeout_millis=5_000)
        _tracer_provider.shutdown()


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 200:
        return "unmatched"
    return path


class ObservabilityMiddleware:
    """Measure and trace requests without labeling raw paths or identities."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "").upper()
        method_label = method if method in _HTTP_METHODS else "OTHER"
        request_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])
        }
        supplied_id = request_headers.get("x-request-id", "")
        request_id = supplied_id if _REQUEST_ID_RE.fullmatch(supplied_id) else str(uuid.uuid4())
        token = _correlation_id.set(request_id)
        status_code = 500
        started = time.perf_counter()
        _HTTP_INFLIGHT.inc()
        context = propagate.extract(request_headers)

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status") or 500)
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            with _tracer.start_as_current_span(
                "http.request",
                context=context,
                kind=trace.SpanKind.SERVER,
            ) as span:
                span.set_attribute("http.request.method", method_label)
                try:
                    await self.app(scope, receive, send_wrapper)
                except BaseException as exc:
                    span.record_exception(exc)
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                    raise
                finally:
                    route = _route_template(scope)
                    span.update_name(f"{method_label} {route}")
                    span.set_attribute("http.route", route)
                    span.set_attribute("http.response.status_code", status_code)
        finally:
            duration = max(0.0, time.perf_counter() - started)
            route = _route_template(scope)
            status_class = f"{max(1, min(status_code // 100, 5))}xx"
            _HTTP_REQUESTS.labels(
                method=method_label,
                route=route,
                status_class=status_class,
            ).inc()
            _HTTP_DURATION.labels(method=method_label, route=route).observe(duration)
            _HTTP_INFLIGHT.dec()
            _correlation_id.reset(token)
