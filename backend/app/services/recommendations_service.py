"""Model recommendations from usage profile and catalog pricing."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.activity_service import ACTIVITY_CHART_COLORS, _bucket_key, _chart_label
from app.services.model_capabilities import model_kinds

RECOMMENDATION_DAYS = 30
TOP_PICKS = 6
MIN_CUSTOM_RANGE_DAYS = 3
ALLOWED_PERIOD_DAYS = frozenset({7, 14, 30, 60, 90})
EXCLUDED_MODEL_IDS = frozenset({"openrouter/auto", "auto"})


@dataclass
class UsageProfile:
    primary_model: str | None
    dominant_kind: str
    avg_prompt_tokens: float
    avg_completion_tokens: float
    p95_prompt_tokens: float
    input_ratio: float
    output_ratio: float
    total_requests: int
    top_models: list[str]

    @property
    def has_usage(self) -> bool:
        return self.total_requests > 0


def _short_label(model_id: str) -> str:
    raw = (model_id or "unknown").strip()
    if "/" in raw:
        raw = raw.split("/")[-1]
    return raw[:48] if len(raw) > 48 else raw


def _is_excluded_model(model_id: str) -> bool:
    mid = (model_id or "").strip().lower()
    return not mid or mid in EXCLUDED_MODEL_IDS or mid.endswith("/auto")


def _quality_tier_score(external_id: str, context_length: int | None) -> float:
    ext = (external_id or "").lower()
    score = 50.0
    tier_rules: tuple[tuple[float, tuple[str, ...]], ...] = (
        (95.0, ("opus-4.8", "opus-4", "o3-pro", "o1-pro", "gpt-4.5")),
        (90.0, ("claude-opus", "/opus", "o3-mini", "/o3", "/o1", "gpt-4.1", "gemini-2.5-pro")),
        (85.0, ("sonnet-4", "claude-sonnet-4", "gpt-4o", "gemini-2.5", "deepseek-r1")),
        (80.0, ("sonnet", "gpt-4", "gemini-pro", "deepseek-v3", "qwen-max")),
        (72.0, ("haiku", "mini", "flash", "lite", "turbo")),
        (65.0, ("gpt-3.5", "llama-3.1-8b", "llama-3.2-3b", "8b-instruct")),
    )
    for pts, needles in tier_rules:
        if any(n in ext for n in needles):
            score = max(score, pts)
    if any(x in ext for x in ("nano", "free", "1b", "3b")):
        score = min(score, 68.0)
    if context_length and context_length > 0:
        score += min(10.0, (context_length / 200_000) * 10)
    return min(100.0, round(score, 1))


def _blended_cost_per_1k(model: AIModel, input_ratio: float, output_ratio: float) -> float:
    inp = float(model.input_cost_per_1k or 0)
    out = float(model.output_cost_per_1k or inp)
    return max(0.000_001, inp * input_ratio + out * output_ratio)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def _model_kind(model: AIModel) -> str:
    kinds = model_kinds(
        external_id=model.external_id,
        is_image_model=bool(model.is_image_model),
        pricing_raw=model.pricing_raw,
    )
    if "text" in kinds:
        return "text"
    if "image" in kinds:
        return "image"
    return kinds[0] if kinds else "text"


def build_usage_profile(rows: list[RequestLog], catalog: dict[str, AIModel]) -> UsageProfile:
    if not rows:
        return UsageProfile(
            primary_model=None,
            dominant_kind="text",
            avg_prompt_tokens=800.0,
            avg_completion_tokens=400.0,
            p95_prompt_tokens=2000.0,
            input_ratio=0.65,
            output_ratio=0.35,
            total_requests=0,
            top_models=[],
        )

    kind_counts: dict[str, int] = defaultdict(int)
    model_counts: dict[str, int] = defaultdict(int)
    prompts: list[float] = []
    completions: list[float] = []
    total_prompt = 0.0
    total_completion = 0.0

    for r in rows:
        mid = (r.model_id or "").strip()
        if _is_excluded_model(mid):
            continue
        model_counts[mid] += 1
        cat = catalog.get(mid)
        kind = _model_kind(cat) if cat else "text"
        kind_counts[kind] += 1
        pt = float(r.prompt_tokens or 0)
        ct = float(r.completion_tokens or 0)
        prompts.append(pt)
        completions.append(ct)
        total_prompt += pt
        total_completion += ct

    dominant_kind = max(kind_counts.items(), key=lambda x: x[1])[0] if kind_counts else "text"
    top_models = [m for m, _ in sorted(model_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
    primary = top_models[0] if top_models else None
    total_tokens = total_prompt + total_completion
    input_ratio = total_prompt / total_tokens if total_tokens > 0 else 0.65
    output_ratio = 1.0 - input_ratio

    return UsageProfile(
        primary_model=primary,
        dominant_kind=dominant_kind,
        avg_prompt_tokens=total_prompt / len(rows) if rows else 800.0,
        avg_completion_tokens=total_completion / len(rows) if rows else 400.0,
        p95_prompt_tokens=_percentile(prompts, 95) or 2000.0,
        input_ratio=input_ratio,
        output_ratio=output_ratio,
        total_requests=len(rows),
        top_models=top_models,
    )


def _user_model_stats(rows: list[RequestLog]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = defaultdict(lambda: {"requests": 0.0, "success": 0.0, "latency_ms": 0.0})
    for r in rows:
        mid = (r.model_id or "").strip()
        if _is_excluded_model(mid):
            continue
        stats[mid]["requests"] += 1
        if r.success:
            stats[mid]["success"] += 1
        stats[mid]["latency_ms"] += float(r.response_time_ms or 0)
    for mid, s in stats.items():
        n = s["requests"] or 1
        s["success_rate"] = s["success"] / n
        s["avg_latency_ms"] = s["latency_ms"] / n
    return stats


def _fit_score(model: AIModel, profile: UsageProfile, user_stats: dict[str, dict[str, float]]) -> float:
    base = _quality_tier_score(model.external_id, model.context_length)
    kind = _model_kind(model)
    if kind != profile.dominant_kind:
        base -= 25.0
    ctx = model.context_length or 0
    if ctx >= profile.p95_prompt_tokens:
        base += 3.0
    elif ctx < profile.p95_prompt_tokens * 0.5:
        base -= 5.0
    ust = user_stats.get(model.external_id)
    if ust and ust.get("requests", 0) >= 3:
        if ust.get("success_rate", 0) >= 0.95:
            base += 2.0
        elif ust.get("success_rate", 0) < 0.8:
            base -= 4.0
    return max(0.0, min(100.0, round(base, 1)))


def _pick_reason(kind: str, fit: float, primary_quality: float | None, blended: float, primary_cost: float | None) -> str:
    if kind == "quality":
        if primary_quality is not None and fit > primary_quality + 5:
            return f"Higher capability tier (+{round(fit - primary_quality)} match vs your main model)"
        if fit >= 90:
            return "Top-tier model for your usage pattern"
        return "Strong fit for your typical requests"
    if primary_cost and blended < primary_cost:
        pct = round((1 - blended / primary_cost) * 100)
        if pct > 0:
            return f"~{pct}% lower estimated cost at similar capability"
    return "Best cost-to-capability ratio for your token mix"


def _score_candidates(
    catalog_models: list[AIModel],
    profile: UsageProfile,
    user_stats: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    primary = profile.primary_model
    primary_model = next((m for m in catalog_models if m.external_id == primary), None)
    primary_quality = _fit_score(primary_model, profile, user_stats) if primary_model else None
    primary_cost = (
        _blended_cost_per_1k(primary_model, profile.input_ratio, profile.output_ratio) if primary_model else None
    )

    scored: list[dict[str, Any]] = []
    for model in catalog_models:
        if not model.is_enabled or _is_excluded_model(model.external_id):
            continue
        if _model_kind(model) != profile.dominant_kind:
            continue
        fit = _fit_score(model, profile, user_stats)
        blended = _blended_cost_per_1k(model, profile.input_ratio, profile.output_ratio)
        value_index = round((fit / blended) * 10, 1) if blended > 0 else 0.0
        savings_pct: float | None = None
        if primary_cost and primary_cost > 0:
            savings_pct = round(max(0.0, (1 - blended / primary_cost) * 100), 1)
        scored.append(
            {
                "model_id": model.external_id,
                "label": _short_label(model.display_name or model.external_id),
                "fit_score": fit,
                "value_index": value_index,
                "blended_cost_per_1k": round(blended, 6),
                "context_length": model.context_length,
                "input_cost_per_1k": model.input_cost_per_1k,
                "output_cost_per_1k": model.output_cost_per_1k,
                "primary_quality": primary_quality,
                "savings_pct": savings_pct,
                "quality_reason": _pick_reason("quality", fit, primary_quality, blended, primary_cost),
                "value_reason": _pick_reason("value", fit, primary_quality, blended, primary_cost),
            }
        )
    return scored


def _select_quality_picks(scored: list[dict[str, Any]], profile: UsageProfile) -> list[dict[str, Any]]:
    primary = profile.primary_model
    primary_fit = next((s["fit_score"] for s in scored if s["model_id"] == primary), 0.0)
    pool = [s for s in scored if s["model_id"] != primary]
    pool.sort(key=lambda x: x["fit_score"], reverse=True)
    picks = pool[:TOP_PICKS]
    if not picks:
        picks = sorted(scored, key=lambda x: x["fit_score"], reverse=True)[:TOP_PICKS]
    if primary and primary_fit > 0 and all(p["fit_score"] < primary_fit for p in picks):
        top = max(scored, key=lambda x: x["fit_score"])
        if top["model_id"] != primary:
            picks = [top, *[p for p in picks if p["model_id"] != top["model_id"]][: TOP_PICKS - 1]]
    return picks[:TOP_PICKS]


def _select_value_picks(scored: list[dict[str, Any]], profile: UsageProfile) -> list[dict[str, Any]]:
    primary = profile.primary_model
    primary_fit = next((s["fit_score"] for s in scored if s["model_id"] == primary), 70.0)
    floor = max(55.0, primary_fit * 0.8)
    pool = [
        s
        for s in scored
        if s["model_id"] != primary and s["fit_score"] >= floor and s["blended_cost_per_1k"] > 0
    ]
    pool.sort(key=lambda x: (x["value_index"], x["fit_score"]), reverse=True)
    picks = pool[:TOP_PICKS]
    if not picks:
        picks = sorted(scored, key=lambda x: x["value_index"], reverse=True)[:TOP_PICKS]
    return picks[:TOP_PICKS]


def _build_chart_rows(
    rows: list[RequestLog],
    picks: list[dict[str, Any]],
    *,
    since: datetime,
    now: datetime,
    metric: str,
) -> list[dict[str, Any]]:
    keys = [p["model_id"] for p in picks]
    key_set = set(keys)
    tz_mode = "local"
    bucket_data: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for r in rows:
        mid = (r.model_id or "").strip()
        if mid not in key_set:
            continue
        bkey = _bucket_key(r.request_time or now, "month", tz_mode)
        if metric == "spend":
            bucket_data[bkey][mid] += float(r.total_cost_usd or 0)
        elif metric == "score":
            pick = next((p for p in picks if p["model_id"] == mid), None)
            bucket_data[bkey][mid] += float(pick["fit_score"] if pick else 0)
        else:
            bucket_data[bkey][mid] += float((r.prompt_tokens or 0) + (r.completion_tokens or 0))

    start = since
    chart: list[dict[str, Any]] = []
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        bkey = _bucket_key(cursor, "month", tz_mode)
        row: dict[str, Any] = {"label": _chart_label(bkey, "month", tz_mode)}
        for mid in keys:
            row[_segment_key(mid)] = bucket_data[bkey].get(mid, 0.0)
        chart.append(row)
        cursor += timedelta(days=1)
    return chart


def _segment_key(model_id: str) -> str:
    return model_id.replace("/", "__").replace(".", "_")[:64]


def _card_payload(
    *,
    card_id: str,
    title: str,
    picks: list[dict[str, Any]],
    rows: list[RequestLog],
    since: datetime,
    now: datetime,
    metric: str,
    value_field: str,
    total_format: str,
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    for idx, pick in enumerate(picks):
        seg_key = _segment_key(pick["model_id"])
        segments.append(
            {
                "key": seg_key,
                "label": pick["label"],
                "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                "value": pick[value_field],
                "model_id": pick["model_id"],
                "reason": pick["quality_reason"] if card_id == "quality" else pick["value_reason"],
                "fit_score": pick["fit_score"],
                "value_index": pick["value_index"],
                "savings_pct": pick.get("savings_pct"),
                "blended_cost_per_1k": pick["blended_cost_per_1k"],
            }
        )

    chart = _build_chart_rows(rows, picks, since=since, now=now, metric=metric)
    if value_field == "fit_score":
        total = round(max((p["fit_score"] for p in picks), default=0), 1)
        unit = "% match"
    else:
        best = picks[0] if picks else None
        total = best["savings_pct"] if best and best.get("savings_pct") is not None else 0
        unit = "% savings"
        total_format = "savings"

    return {
        "id": card_id,
        "title": title,
        "total": total,
        "unit": unit,
        "total_format": total_format,
        "segments": segments,
        "chart": chart,
    }


def _inclusive_day_count(since: datetime, until: datetime) -> int:
    return max(1, (until.date() - since.date()).days + 1)


def build_recommendations_payload(
    *,
    rows: list[RequestLog],
    catalog_models: list[AIModel],
    now: datetime | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    period_days: int | None = None,
    period_mode: str = "preset",
    period_from: str | None = None,
    period_to: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()
    until = until or now
    if since is None:
        days = period_days if period_days in ALLOWED_PERIOD_DAYS else RECOMMENDATION_DAYS
        since = now - timedelta(days=days)
        period_days = days
    else:
        period_days = period_days or _inclusive_day_count(since, until)

    usage_rows = [
        r
        for r in rows
        if r.request_time and since <= r.request_time <= until
    ]

    catalog_by_id = {m.external_id: m for m in catalog_models}
    profile = build_usage_profile(usage_rows, catalog_by_id)
    user_stats = _user_model_stats(usage_rows)
    scored = _score_candidates(catalog_models, profile, user_stats)
    quality_picks = _select_quality_picks(scored, profile)
    value_picks = _select_value_picks(scored, profile)

    if period_mode == "custom" and period_from and period_to:
        range_label = f"{period_from} to {period_to}"
    else:
        range_label = f"the last {period_days} days"

    if profile.has_usage:
        msg = (
            f"Based on your {profile.dominant_kind} usage in {range_label}"
            + (f" (main model: {_short_label(profile.primary_model or '')})." if profile.primary_model else ".")
        )
    else:
        msg = f"No usage in {range_label} — showing top {profile.dominant_kind} models from the catalog."

    quality_card = _card_payload(
        card_id="quality",
        title="Highest quality for you",
        picks=quality_picks,
        rows=usage_rows,
        since=since,
        now=now,
        metric="tokens",
        value_field="fit_score",
        total_format="match",
    )
    value_card = _card_payload(
        card_id="value",
        title="Best value for you",
        picks=value_picks,
        rows=usage_rows,
        since=since,
        now=now,
        metric="spend",
        value_field="value_index",
        total_format="savings",
    )

    return {
        "period_days": period_days,
        "period": {
            "mode": period_mode,
            "days": period_days,
            "from": period_from,
            "to": period_to,
        },
        "message": msg,
        "profile": {
            "primary_model": profile.primary_model,
            "primary_model_label": _short_label(profile.primary_model or "") if profile.primary_model else None,
            "dominant_kind": profile.dominant_kind,
            "avg_prompt_tokens": int(round(profile.avg_prompt_tokens)),
            "avg_completion_tokens": int(round(profile.avg_completion_tokens)),
            "total_requests": profile.total_requests,
            "top_models": profile.top_models,
        },
        "quality": quality_card,
        "value": value_card,
    }
