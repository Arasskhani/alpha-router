"""Bounded Prometheus metrics, OpenTelemetry tracing, and safe JSON logs."""

from __future__ import annotations

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
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_KNOWN_EVENTS = frozenset(
    {
        "redis_fallback",
        "broker_failure",
        "ssrf_block",
        "csrf_failure",
        "repeated_401",
        "budget_hold_leak",
        "code_interpreter_capacity_rejected",
        "code_interpreter_lease_expired",
        "code_interpreter_cancelled",
        "docs_denied",
        "production_guard_warning",
        "sandbox_orphan_removed",
        "video_job_started",
        "video_provider_submit",
        "video_job_completed",
        "video_job_failed",
        "agent_run_failed",
        "agent_run_blocked",
        "agent_retrieval_unavailable",
        "evaluation_gate_failed",
        "evaluation_gate_passed",
        "knowledge_job_dead",
        "retention_purge_blocked",
    }
)
_lock = Lock()
_counts: Counter[str] = Counter()
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "alpharouter_correlation_id",
    default="",
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
)
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
_EVALUATION_STATUSES = frozenset(
    {"awaiting_review", "passed", "failed", "error", "cancelled"}
)
_DEPENDENCIES = frozenset(
    {"postgres", "redis", "qdrant", "seaweedfs", "clamav", "provider"}
)
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
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        supplied_id = request_headers.get("x-request-id", "")
        request_id = (
            supplied_id
            if _REQUEST_ID_RE.fullmatch(supplied_id)
            else str(uuid.uuid4())
        )
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
