"""Tests for model recommendation scoring."""

from datetime import datetime, timedelta

from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.recommendations_service import (
    build_recommendations_payload,
    build_usage_profile,
    _quality_tier_score,
)


def _model(external_id: str, *, inp: float, out: float, ctx: int = 128_000) -> AIModel:
    return AIModel(
        external_id=external_id,
        display_name=external_id.split("/")[-1],
        provider_type="openrouter",
        is_enabled=True,
        input_cost_per_1k=inp,
        output_cost_per_1k=out,
        context_length=ctx,
    )


def _log(model_id: str, *, prompt: int = 1000, completion: int = 500, cost: float = 0.01) -> RequestLog:
    return RequestLog(
        model_id=model_id,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_cost_usd=cost,
        request_time=datetime.utcnow() - timedelta(days=1),
        success=True,
    )


def test_quality_tier_prefers_opus_over_mini():
    assert _quality_tier_score("anthropic/claude-opus-4", 200_000) > _quality_tier_score("openai/gpt-4o-mini", 128_000)


def test_usage_profile_from_logs():
    catalog = {
        "vendor/cheap": _model("vendor/cheap", inp=0.1, out=0.2),
        "vendor/premium": _model("vendor/premium", inp=1.0, out=2.0),
    }
    rows = [_log("vendor/cheap")] * 8 + [_log("vendor/premium")] * 2
    profile = build_usage_profile(rows, catalog)
    assert profile.primary_model == "vendor/cheap"
    assert profile.total_requests == 10
    assert profile.dominant_kind == "text"


def test_recommendations_returns_quality_and_value_cards():
    catalog = [
        _model("openai/gpt-4o-mini", inp=0.15, out=0.6),
        _model("anthropic/claude-opus-4", inp=15.0, out=75.0),
        _model("anthropic/claude-sonnet-4", inp=3.0, out=15.0),
        _model("vendor/budget", inp=0.05, out=0.1),
    ]
    rows = [_log("openai/gpt-4o-mini", prompt=2000, completion=800)] * 20
    payload = build_recommendations_payload(rows=rows, catalog_models=catalog)
    assert payload["quality"]["title"] == "Highest quality for you"
    assert payload["value"]["title"] == "Best value for you"
    assert len(payload["quality"]["segments"]) >= 1
    assert len(payload["value"]["segments"]) >= 1
    quality_ids = {s["model_id"] for s in payload["quality"]["segments"]}
    assert "anthropic/claude-opus-4" in quality_ids
    value_ids = {s["model_id"] for s in payload["value"]["segments"]}
    assert payload["profile"]["primary_model"] == "openai/gpt-4o-mini"
    assert "openai/gpt-4o-mini" not in value_ids
    assert "vendor/budget" in value_ids or "anthropic/claude-sonnet-4" in value_ids


def test_cold_start_uses_catalog_defaults():
    catalog = [
        _model("anthropic/claude-opus-4", inp=15.0, out=75.0),
        _model("vendor/budget", inp=0.05, out=0.1),
    ]
    payload = build_recommendations_payload(rows=[], catalog_models=catalog)
    assert payload["profile"]["total_requests"] == 0
    assert len(payload["quality"]["segments"]) >= 1
    assert len(payload["value"]["segments"]) >= 1


def test_custom_period_range():
    catalog = [_model("openai/gpt-4o-mini", inp=0.15, out=0.6)]
    now = datetime.utcnow()
    since = now - timedelta(days=6)
    rows = [_log("openai/gpt-4o-mini")] * 5
    payload = build_recommendations_payload(
        rows=rows,
        catalog_models=catalog,
        now=now,
        since=since,
        until=now,
        period_days=7,
        period_mode="custom",
        period_from="2025-01-01",
        period_to="2025-01-07",
    )
    assert payload["period"]["mode"] == "custom"
    assert payload["period"]["from"] == "2025-01-01"
    assert "2025-01-01" in payload["message"]
