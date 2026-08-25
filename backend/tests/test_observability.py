"""Bounded, non-sensitive observability metrics and structured logs."""

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.observability import (
    JsonLogFormatter,
    ObservabilityMiddleware,
    increment,
    observe_memory_extract_job,
    observe_memory_item,
    observe_memory_retrieval,
    observe_memory_retrieval_fallback,
    prometheus_payload,
    record_agent_run,
    record_evaluation_run,
    reset,
    snapshot,
)


def test_observability_exposes_only_known_counters():
    reset()
    increment("redis_fallback")
    increment("user_controlled_label")

    counters = snapshot()
    assert counters["redis_fallback"] == 1
    assert counters["csrf_failure"] == 0
    assert "user_controlled_label" not in counters
    reset()


def test_prometheus_metrics_use_bounded_labels_only():
    reset()
    record_agent_run(
        status="succeeded",
        routing_outcome="routed",
        retrieval_outcome="succeeded",
        private_mode=False,
        latency_ms=250,
        cost_usd=0.01,
    )
    record_agent_run(
        status="attacker-controlled-status",
        routing_outcome="attacker-controlled-route",
        retrieval_outcome="attacker-controlled-retrieval",
        private_mode=True,
        latency_ms=100,
        cost_usd=0,
    )
    record_evaluation_run(status="passed", trigger="ci")
    payload, content_type = prometheus_payload()
    text = payload.decode()
    assert "text/plain" in content_type
    assert "alpharouter_agent_runs_total" in text
    assert 'status="succeeded"' in text
    assert 'status="other"' in text
    assert "attacker-controlled" not in text
    assert "alpharouter_evaluation_runs_total" in text
    reset()


def test_http_middleware_labels_route_template_not_raw_identifier():
    test_app = FastAPI()
    test_app.add_middleware(ObservabilityMiddleware)

    @test_app.get("/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    with TestClient(test_app) as client:
        response = client.get("/items/private-user-123")
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    payload, _ = prometheus_payload()
    text = payload.decode()
    assert 'route="/items/{item_id}"' in text
    assert "private-user-123" not in text
    reset()


def test_json_formatter_excludes_arbitrary_sensitive_attributes():
    record = logging.LogRecord(
        name="alpharouter.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="safe event",
        args=(),
        exc_info=None,
    )
    record.secret_token = "must-not-be-exported"
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "safe event"
    assert "secret_token" not in payload
    assert "must-not-be-exported" not in json.dumps(payload)


def test_memory_metrics_use_bounded_labels_only():
    reset()
    observe_memory_extract_job(outcome="succeeded", duration_seconds=0.2)
    observe_memory_extract_job(outcome="attacker-controlled", duration_seconds=0.1)
    observe_memory_item("add")
    observe_memory_item("user-content-should-not-leak")
    payload, _ = prometheus_payload()
    text = payload.decode()
    assert "alpharouter_memory_extract_jobs_total" in text
    assert 'outcome="succeeded"' in text
    assert 'outcome="other"' in text
    assert "attacker-controlled" not in text
    assert "alpharouter_memory_items_total" in text
    assert 'op="add"' in text
    assert "user-content-should-not-leak" not in text
    reset()


def test_memory_metrics_separate_user_and_project_scope():
    reset()
    observe_memory_extract_job(
        outcome="succeeded", duration_seconds=0.2, scope="project"
    )
    observe_memory_item("add", scope="project")
    observe_memory_item("add")
    observe_memory_retrieval(duration_seconds=0.01, injected=3, scope="project")
    observe_memory_retrieval_fallback("unavailable", scope="project")
    # A scope value from anywhere but our own call sites must not create a series.
    observe_memory_item("add", scope="tenant-controlled")
    payload, _ = prometheus_payload()
    text = payload.decode()
    assert 'scope="project"' in text
    assert 'scope="user"' in text
    assert 'scope="other"' in text
    assert "tenant-controlled" not in text
    # Prometheus counters live for the process, so assert on the series shape
    # rather than a value another test in this process may have bumped.
    assert 'alpharouter_memory_items_total{op="add",scope="project"}' in text
    assert 'alpharouter_memory_items_total{op="add",scope="user"}' in text
    assert (
        "alpharouter_memory_retrieval_fallback_total"
        '{reason="unavailable",scope="project"}' in text
    )
    reset()


