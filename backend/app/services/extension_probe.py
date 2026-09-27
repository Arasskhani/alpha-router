"""The browser_control probe: can this model drive a page by pointing at it?

Full control gives the agent a real mouse and screenshots, and a model that
cannot read a screenshot and point at the right place wastes clicks and
approvals. Before an administrator lists a model for screenshots, the probe
shows it a made-up page - three buttons on a plain background, at places
drawn from a seed - and asks it, with the agent's own ``computer`` tool, to
click one of them by its label. A trial passes when the click lands inside
that button. A few trials at different places give the accuracy; the model
also has to answer with a tool call at all (tool calling), or nothing else
is judged.

Nothing of a real page is involved, and the probe costs what three small
vision calls cost, billed to the administrator who ran it, like the reviewer
is billed to the person. The last result per model is kept in
``system_settings`` for the page to show.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import logging
import random
from dataclasses import asdict, dataclass
from typing import Any, cast

from litellm import acompletion
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import EXTENSION_CLIENT_APP
from app.models.system import SystemSetting
from app.models.user import User
from app.services.failure_details import failure_message
from app.services.llm_providers import litellm_model_for_provider
from app.services.model_capabilities import supports_vision
from app.services.model_resolution_service import resolve_model_and_key
from app.services.provider_utils import apply_litellm_provider_kwargs
from app.services.usage_logging_service import reserve_auxiliary_llm_usage, settle_auxiliary_usage

logger = logging.getLogger(__name__)

PROBES_KEY = "extension.probes"
PROBE_OPERATION = "extension_probe"
PROBE_MAX_TOKENS = 200
#: Trials per probe, and what counts as passing.
TRIALS = 3
PASS_HITS = 2

WIDTH, HEIGHT = 640, 400
BUTTON_W, BUTTON_H = 150, 44
LABELS = ("Cancel", "Continue", "Help")
TARGET = "Continue"

#: The agent's own tool, as the extension offers it, cut to the one action the probe asks for.
COMPUTER_TOOL = {
    "type": "function",
    "function": {
        "name": "computer",
        "description": "Use the mouse on the page shown in the screenshot.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["left_click"]},
                "coordinate": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[x, y] in the screenshot's pixels.",
                },
            },
            "required": ["action", "coordinate"],
        },
    },
}

SYSTEM = (
    "You control a web page through screenshots. You answer only by calling the computer tool with "
    "action left_click and the pixel coordinate of the point to click, inside the screenshot you are shown."
)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height


@dataclass(frozen=True)
class ProbePage:
    """One made-up page: its PNG, and where the target button is."""

    png: bytes
    target: Box
    seed: int


@dataclass(frozen=True)
class Trial:
    seed: int
    called: bool
    x: int | None
    y: int | None
    hit: bool
    error: str | None = None


@dataclass(frozen=True)
class ProbeResult:
    model_ref: str
    ran_at: str
    vision: bool
    tool_calling: bool
    hits: int
    trials: int
    passed: bool
    detail: str
    results: tuple[Trial, ...] = ()

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = [asdict(t) for t in self.results]
        return data


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow: one size only
        return ImageFont.load_default()


def probe_page(seed: int) -> ProbePage:
    """The page for one trial: three labelled buttons, placed by the seed so no two trials look alike."""
    rng = random.Random(seed)
    image = Image.new("RGB", (WIDTH, HEIGHT), (246, 247, 249))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH, 56], fill=(31, 36, 48))
    draw.text((20, 18), "Account settings", fill=(255, 255, 255), font=_font(18))
    for y in (110, 150, 190):
        draw.rounded_rectangle([40, y, WIDTH - 40, y + 26], radius=6, fill=(225, 228, 233))
    labels = list(LABELS)
    rng.shuffle(labels)
    # Three columns; each button lands somewhere in its column, in the lower half of the page.
    column = (WIDTH - 80) // 3
    target: Box | None = None
    for index, label in enumerate(labels):
        x = 40 + index * column + rng.randint(0, max(0, column - BUTTON_W - 10))
        y = 250 + rng.randint(0, HEIGHT - 250 - BUTTON_H - 20)
        box = Box(x, y, BUTTON_W, BUTTON_H)
        # Every button looks the same: only its label tells it apart, which is what the model has to read.
        draw.rounded_rectangle(
            [box.x, box.y, box.x + box.width, box.y + box.height],
            radius=8,
            fill=(255, 255, 255),
            outline=(170, 175, 183),
            width=2,
        )
        font = _font(17)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        draw.text(
            (box.x + (box.width - (right - left)) / 2, box.y + (box.height - (bottom - top)) / 2 - top / 2),
            label,
            fill=(40, 44, 52),
            font=font,
        )
        if label == TARGET:
            target = box
    assert target is not None
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return ProbePage(png=out.getvalue(), target=target, seed=seed)


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def parse_click(response: Any) -> tuple[int, int] | None:
    """The point the model clicked, from its tool call; None when it did not call the tool usably."""
    try:
        choice = response.choices[0]
        calls = getattr(choice.message, "tool_calls", None) or []
    except (AttributeError, IndexError, TypeError):
        return None
    for call in calls:
        function = getattr(call, "function", None)
        if getattr(function, "name", None) != "computer":
            continue
        try:
            args = json.loads(getattr(function, "arguments", "") or "{}")
        except ValueError:
            return None
        if not isinstance(args, dict) or args.get("action") != "left_click":
            return None
        point = args.get("coordinate")
        if not isinstance(point, list) or len(point) != 2:
            return None
        try:
            x, y = int(point[0]), int(point[1])
        except (TypeError, ValueError):
            return None
        return (x, y)
    return None


async def _one_trial(
    db: AsyncSession,
    user: User,
    ai_model: Any,
    provider: str | None,
    model: str,
    api_key: str,
    base_url: str | None,
    seed: int,
) -> Trial:
    page = probe_page(seed)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"This screenshot is {WIDTH} by {HEIGHT} pixels. Click the button labelled {TARGET}.",
                },
                {"type": "image_url", "image_url": {"url": _data_url(page.png)}},
            ],
        },
    ]
    kwargs: dict[str, Any] = {
        "messages": messages,
        "api_key": api_key,
        "base_url": base_url,
        "stream": False,
        "max_tokens": PROBE_MAX_TOKENS,
        "temperature": 0,
        "timeout": 45.0,
        "tools": [COMPUTER_TOOL],
        "tool_choice": "auto",
    }
    apply_litellm_provider_kwargs(kwargs, provider, model)
    try:
        reservation_id = await reserve_auxiliary_llm_usage(
            db,
            user_id=int(user.id),
            ai_model=ai_model,
            operation_name=PROBE_OPERATION,
            messages=messages,
            max_tokens=PROBE_MAX_TOKENS,
        )
    except Exception:  # noqa: BLE001 -- a refused hold (budget) ends the trial, not the server
        logger.info("extension probe not reserved", exc_info=True)
        return Trial(seed=seed, called=False, x=None, y=None, hit=False, error="Your budget does not cover the probe.")
    response = None
    completion = ""
    success = False
    error_message: str | None = None
    started_at = datetime.datetime.utcnow()
    try:
        response = await acompletion(**kwargs)
        completion = (
            json.dumps([c.function.arguments for c in (getattr(response.choices[0].message, "tool_calls", None) or [])])
            if response.choices
            else ""
        )
        success = True
    except Exception as exc:  # noqa: BLE001 -- the trial fails; the reason is shown
        error_message = failure_message(exc)[:500]
        return Trial(
            seed=seed, called=False, x=None, y=None, hit=False, error=error_message or "The model could not be reached."
        )
    finally:
        await settle_auxiliary_usage(
            user_id=int(user.id),
            username=str(user.username),
            ai_model=ai_model,
            provider_type=provider,
            model_id=model,
            response=response,
            prompt=messages,
            completion=completion,
            operation_name=PROBE_OPERATION,
            client_app=f"{EXTENSION_CLIENT_APP} (helper:probe)",
            budget_reservation_id=reservation_id,
            success=success,
            error_message=error_message,
            started_at=started_at,
        )
    point = parse_click(response)
    if point is None:
        return Trial(seed=seed, called=False, x=None, y=None, hit=False)
    return Trial(seed=seed, called=True, x=point[0], y=point[1], hit=page.target.contains(*point))


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def run_probe(
    db: AsyncSession, *, user: User, model_ref: str, seeds: tuple[int, ...] | None = None
) -> ProbeResult:
    """Probe one model; the result, also kept for the page. The caller commits."""
    ai_model, api_key, base_url, provider_type = await resolve_model_and_key(db, model_ref)
    if ai_model is None or not api_key:
        return await keep_result(
            db, ProbeResult(model_ref, _now(), False, False, 0, 0, False, "The model is not available.")
        )
    ref = f"model::{ai_model.id}"
    provider = cast("str | None", provider_type or ai_model.provider_type)
    vision = supports_vision(
        external_id=str(ai_model.external_id or ""),
        is_image_model=bool(ai_model.is_image_model),
        pricing_raw=cast("str | None", ai_model.pricing_raw),
        provider_type=provider,
    )
    if not vision:
        return await keep_result(
            db, ProbeResult(ref, _now(), False, False, 0, 0, False, "This model does not read images.")
        )
    model = litellm_model_for_provider(str(ai_model.external_id or ""), provider)
    chosen = seeds or tuple(random.Random().randrange(1, 1_000_000) for _ in range(TRIALS))
    trials: list[Trial] = []
    for seed in chosen:
        trials.append(await _one_trial(db, user, ai_model, provider, model, api_key, base_url, seed))
    called = sum(1 for t in trials if t.called)
    hits = sum(1 for t in trials if t.hit)
    errors = [t.error for t in trials if t.error]
    if errors and called == 0:
        detail = errors[0] or "The probe could not run."
    elif called == 0:
        detail = "The model answered without calling the tool: it cannot drive the browser."
    else:
        detail = f"Clicked inside the button in {hits} of {len(trials)} trials."
    result = ProbeResult(
        model_ref=ref,
        ran_at=_now(),
        vision=True,
        tool_calling=called > 0,
        hits=hits,
        trials=len(trials),
        passed=called == len(trials) and hits >= PASS_HITS,
        detail=detail,
        results=tuple(trials),
    )
    return await keep_result(db, result)


async def load_results(db: AsyncSession) -> dict[str, dict[str, Any]]:
    """The last probe result per model, as stored."""
    row = await db.get(SystemSetting, PROBES_KEY)
    if row is None or not row.value:
        return {}
    try:
        data = json.loads(cast("str", row.value))
    except (TypeError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


async def keep_result(db: AsyncSession, result: ProbeResult) -> ProbeResult:
    """Store the result under its model; the page shows the last one. The caller commits."""
    results = await load_results(db)
    kept = result.to_json()
    kept.pop("results", None)
    results[result.model_ref] = kept
    value = json.dumps(results, separators=(",", ":"), sort_keys=True)
    if await db.get(SystemSetting, PROBES_KEY) is None:
        db.add(SystemSetting(key=PROBES_KEY, value=value))
    else:
        await db.execute(update(SystemSetting).where(SystemSetting.key == PROBES_KEY).values(value=value))
    return result
