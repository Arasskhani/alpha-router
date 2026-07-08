"""Repro OpenRouter long-prompt image gen. Never prints API key or image bytes."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.images import _collect_openrouter_images
from app.config import get_settings
from app.services.openrouter_image_service import (
    build_fast_openrouter_payload,
    build_openrouter_headers,
    post_openrouter_json,
)

LONG_PROMPT = (
    "Cinematic ultra-detailed establishing shot of a rain-soaked neo-noir megacity at blue hour, "
    "viewed from a high rooftop garden overlooking endless glass towers and suspended maglev lines. "
    "In the foreground, a weathered brass telescope on a tripod points toward the skyline; dew beads on "
    "its lenses catch amber streetlight. Midground: a narrow rooftop greenhouse filled with bioluminescent "
    "orchids in violet, cyan, and deep magenta, their glow mixing with cool moonlight. A lone figure in a "
    "translucent raincoat stands beside a humming server rack covered in moss, cables snaking like vines. "
    "Background: colossal holographic billboards display abstract kanji and geometric art; distant lightning "
    "silhouettes thunderheads. Lighting: motivated practicals—warm tungsten from apartment windows, cold "
    "LED strips along walkways, soft rim light from an off-screen drone spotlight. Atmosphere: volumetric fog, "
    "fine rain streaks, subtle lens flare, anamorphic bokeh on distant headlights. Color grade: teal shadows, "
    "orange highlights, crushed blacks with retained micro-contrast. Materials: wet concrete textures, brushed "
    "metal, frosted glass, iridescent puddles reflecting neon signs reading OPEN, Alpha Router, and stylized arrows. "
    "Composition: rule of thirds, leading lines from maglev tracks toward a central spire crowned with a rotating "
    "ring structure. Style: photorealistic concept art, 35mm film grain, shallow depth of field, high dynamic range, "
    "Unreal Engine cinematic quality, art direction by Denis Villeneuve meets Syd Mead. "
    "Additional micro-details: steam vents exhale white plumes; a cat-shaped drone sleeps on a solar panel; "
    "paper lanterns float upward carrying tiny LEDs; graffiti in metallic paint shimmers; wind ripples a reflective "
    "tarp; distant fireworks burst silently in slow motion; chromatic aberration at frame edges; subtle motion blur "
    "on passing trains; ivy climbs a rusted fire escape; a broken neon tube flickers cyan-pink; raindrops on camera "
    "simulate foreground droplets. "
    "Scene storytelling: the figure monitors atmospheric CO2 levels on a wrist HUD showing emerald graphs; a vintage "
    "film camera hangs from their shoulder; scattered blueprints depict floating arcologies; a half-finished cup of "
    "tea steams beside a notebook filled with constellation sketches. "
    "Sky: layered clouds with god rays piercing through; two moons (one pale, one rust-colored) low on horizon. "
    "Water: cascading runoff from rooftop pools forms thin waterfalls into alley mist below. "
    "Crowd life implied but not detailed: silhouettes in windows, distant umbrellas as colorful dots. "
    "Render intent: square 1:1 poster frame, crisp 1K clarity, no text overlays, no watermark, no UI. "
    "Mood: melancholic hope, technological sublime, quiet before a storm. "
    "Repeat texture richness: every surface should show wear, scratches, fingerprints, subtle imperfections, "
    "photographic authenticity, global illumination, ray-traced reflections, accurate subsurface scattering on leaves. "
    "Ensure balanced exposure, no blown highlights, readable shadow detail, harmonious complementary palette. "
    "Final emphasis: hyperreal environment illustration suitable for a blockbuster title card background."
)


def _summarize(label: str, resp: Any, data: dict | None) -> dict[str, Any]:
    out: dict[str, Any] = {"label": label, "http_status": resp.status_code}
    if data is None:
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        out["parse_error"] = type(data).__name__
        return out
    out["top_keys"] = sorted(data.keys())
    out["body_empty"] = len(resp.content or b"") == 0
    choices = data.get("choices") or []
    out["choices_count"] = len(choices)
    fr = None
    nfr = None
    msg_keys: list[str] | None = None
    images_count = 0
    if choices and isinstance(choices[0], dict):
        ch0 = choices[0]
        fr = ch0.get("finish_reason")
        nfr = ch0.get("native_finish_reason")
        msg = ch0.get("message") or {}
        if isinstance(msg, dict):
            msg_keys = sorted(msg.keys())
            imgs = msg.get("images")
            if isinstance(imgs, list):
                images_count = len(imgs)
    collected = _collect_openrouter_images(data) if data else []
    out["finish_reason"] = fr
    out["native_finish_reason"] = nfr
    out["message_keys"] = msg_keys
    out["message_images_count"] = images_count
    out["collected_images_count"] = len(collected)
    out["images_returned"] = len(collected) > 0
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    out["usage"] = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }
    err = data.get("error")
    if err:
        out["error_type"] = err.get("type") if isinstance(err, dict) else str(type(err))
        out["error_message"] = (err.get("message") if isinstance(err, dict) else str(err))[:200]
    return out


def _build_payload(model_id: str, *, with_sort: bool) -> dict:
    p = build_fast_openrouter_payload(
        model_id=model_id,
        prompt=LONG_PROMPT,
        size="1024x1024",
        modalities=["image", "text"],
        aspect_ratio="1:1",
        allow_fallbacks=True,
        image_size_tier="1K",
    )
    if not with_sort:
        p["provider"] = {"allow_fallbacks": True}
    return p


async def _post(api_key: str, base_url: str, payload: dict) -> tuple[Any, dict | None]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = build_openrouter_headers(api_key, referer="https://alpha-router.local")
    resp = await post_openrouter_json(url, headers=headers, json_payload=payload)
    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {}
    return resp, data if isinstance(data, dict) else None


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT api_key_encrypted, base_url FROM connections WHERE id=1 LIMIT 1")
        )).fetchone()
    await engine.dispose()
    if not row:
        print(json.dumps({"error": "connection id=1 not found"}))
        return
    api_key, base_url = row[0], (row[1] or "https://openrouter.ai/api/v1")
    print(json.dumps({
        "step1": "api_key loaded from postgres connections.id=1",
        "prompt_chars": len(LONG_PROMPT),
        "base_url": base_url,
    }))

    model = "google/gemini-3.1-flash-lite-image"

    async def run_burst(with_sort: bool, prefix: str) -> list[dict]:
        nonlocal model
        payload = _build_payload(model, with_sort=with_sort)
        results: list[dict] = []
        for i in range(1, 4):
            resp, data = await _post(api_key, base_url, payload)
            if resp.status_code == 400 and i == 1 and "lite" in model:
                model = "google/gemini-3.1-flash-image"
                payload = _build_payload(model, with_sort=with_sort)
                resp, data = await _post(api_key, base_url, payload)
            results.append({**_summarize(f"{prefix} attempt{i}", resp, data), "model": payload.get("model")})
        return results

    burst_sort = await run_burst(True, "sort_throughput")
    print(json.dumps({"burst_with_sort_throughput": burst_sort}, indent=2))

    a1 = burst_sort[0]
    empty_a1 = (
        a1.get("http_status") == 200
        and not a1.get("images_returned")
        and (a1.get("body_empty") or a1.get("choices_count", 0) == 0 or a1.get("collected_images_count", 0) == 0)
    )
    retry_after_2s = None
    if empty_a1:
        await asyncio.sleep(2)
        payload = _build_payload(model, with_sort=True)
        resp, data = await _post(api_key, base_url, payload)
        retry_after_2s = _summarize("sort_throughput attempt1 retry after 2s", resp, data)
    print(json.dumps({"attempt1_empty_payload": empty_a1, "retry_after_2s": retry_after_2s}, indent=2))

    burst_no_sort = await run_burst(False, "no_sort")
    print(json.dumps({"burst_no_sort": burst_no_sort}, indent=2))

    def success_rate(burst: list[dict]) -> float:
        ok = sum(1 for b in burst if b.get("images_returned"))
        return ok / len(burst) if burst else 0.0

    print(json.dumps({
        "success_rate_with_sort": success_rate(burst_sort),
        "success_rate_no_sort": success_rate(burst_no_sort),
    }))


if __name__ == "__main__":
    asyncio.run(main())
