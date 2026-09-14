"""OpenRouter pricing sentinels must not produce negative logged spend."""

from types import SimpleNamespace

import pytest

from app.services.model_sync import _per_1k_from_openrouter_pricing
from app.services.provider_utils import compute_token_cost_usd as _compute_token_cost_usd
from app.services.provider_utils import sanitize_cost_usd as _sanitize_cost_usd


def test_openrouter_sentinel_pricing_is_unknown():
    in_1k, out_1k = _per_1k_from_openrouter_pricing({"prompt": "-1", "completion": "-1"})
    assert in_1k is None
    assert out_1k is None


def test_openrouter_valid_pricing_normalized_to_per_1k():
    in_1k, out_1k = _per_1k_from_openrouter_pricing({"prompt": "0.000003", "completion": "0.000015"})
    assert in_1k == pytest.approx(0.003)
    assert out_1k == pytest.approx(0.015)


def test_openrouter_tiered_pricing_uses_base_tier():
    tiers = [
        {"prompt": "0.000002", "completion": "0.000012"},
        {"prompt": "0.000004", "completion": "0.000018", "min_context": 200000},
    ]
    in_1k, out_1k = _per_1k_from_openrouter_pricing(tiers)
    assert in_1k == 0.002
    assert out_1k == 0.012


def test_compute_token_cost_rejects_negative_catalog_rates():
    model = SimpleNamespace(input_cost_per_1k=-1000.0, output_cost_per_1k=0.01)
    cost = _compute_token_cost_usd(
        model,
        prompt_tokens=100,
        completion_tokens=3287,
        model_id="test/model",
        messages=[{"role": "user", "content": "hi"}],
        completion_text="hello",
    )
    assert cost >= 0


def test_compute_token_cost_uses_catalog_when_both_rates_valid():
    model = SimpleNamespace(input_cost_per_1k=0.001, output_cost_per_1k=0.002)
    cost = _compute_token_cost_usd(
        model,
        prompt_tokens=1000,
        completion_tokens=500,
        model_id="test/model",
        messages=[{"role": "user", "content": "hi"}],
        completion_text="hello",
    )
    assert cost == 0.002  # 0.001 + 0.001


def test_sanitize_cost_usd_clamps_negative():
    assert _sanitize_cost_usd(-3286.98) == 0.0
    assert _sanitize_cost_usd(1.25) == 1.25
