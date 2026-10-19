"""The chat's Web Search: which service to ask, in what order, and what it cost.

An administrator adds web search connections (Admin → Connections → Web
search), each with a priority and a price per search. A search asks the
active ones in priority order and stops at the first that answers; one that
refuses (a key, a quota, a rate limit, the network) is recorded with its
reason and the next is asked. DuckDuckGo, which needs no key, comes last when
the administrator allows it as a fallback (on by default) and is not already
one of the connections.

Every attempt is metered as ``service_type=web_search`` against the person
or API key, on that connection, at its price, so Admin Logs and the
connection's Activity show each search and each failure with its reason.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.system import SystemSetting
from app.services.connection_kinds import NO_KEY_PROVIDERS, web_search_connection
from app.services.metered_usage_service import finish_metered_usage, start_metered_usage
from app.services.secret_crypto import decrypt_secret
from app.services.web_search_providers import (
    ERROR_NOT_CONFIGURED,
    PROVIDER_LABELS,
    SearchResult,
    SearchTarget,
    WebSearchError,
    run_search,
)

logger = logging.getLogger(__name__)

SETTINGS_KEY = "web_search.settings"
#: The provider_type of the fallback that is no connection.
DUCKDUCKGO = "duckduckgo"


@dataclass(frozen=True)
class WebSearchSettings:
    #: DuckDuckGo after the connections (or alone, when there are none). Off: only the connections are asked.
    duckduckgo_fallback: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"duckduckgo_fallback": self.duckduckgo_fallback}


def parse_web_search_settings(raw: str | None) -> WebSearchSettings:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return WebSearchSettings(duckduckgo_fallback=bool(data.get("duckduckgo_fallback", True)))


async def load_web_search_settings(db: AsyncSession) -> WebSearchSettings:
    row = await db.get(SystemSetting, SETTINGS_KEY)
    return parse_web_search_settings(cast("str | None", row.value) if row is not None else None)


async def save_web_search_settings(db: AsyncSession, settings: WebSearchSettings) -> None:
    """Write the settings; the caller commits (and audits)."""
    value = json.dumps(settings.to_json(), separators=(",", ":"), sort_keys=True)
    row = await db.get(SystemSetting, SETTINGS_KEY)
    if row is None:
        db.add(SystemSetting(key=SETTINGS_KEY, value=value))
    else:
        row.value = value  # type: ignore[assignment]


@dataclass(frozen=True)
class SearchStep:
    """One service a search may ask, in order."""

    target: SearchTarget
    label: str
    connection_id: int | None
    price_usd: float


def connection_target(conn: Connection) -> SearchTarget:
    """What a search connection asks with: its provider, key, address and options."""
    provider = str(conn.provider_type or "").strip().lower()
    try:
        config = json.loads(str(conn.config_json or "{}"))
    except (TypeError, ValueError):
        config = {}
    key = "" if provider in NO_KEY_PROVIDERS else (decrypt_secret(cast("str | None", conn.api_key_encrypted)) or "")
    return SearchTarget(
        provider=provider,
        api_key=key,
        base_url=cast("str | None", conn.base_url),
        config=config if isinstance(config, dict) else {},
    )


async def search_plan(db: AsyncSession) -> list[SearchStep]:
    """The services a search asks, in order: the active connections by priority, then DuckDuckGo if allowed."""
    rows = (
        (
            await db.execute(
                select(Connection)
                .where(web_search_connection(), Connection.is_active.is_(True))
                .order_by(Connection.priority.asc(), Connection.id.asc())
            )
        )
        .scalars()
        .all()
    )
    steps = [
        SearchStep(
            target=connection_target(conn),
            label=str(conn.name or PROVIDER_LABELS.get(str(conn.provider_type), str(conn.provider_type))),
            connection_id=int(conn.id),
            price_usd=float(conn.price_per_request_usd or 0),
        )
        for conn in rows
    ]
    settings = await load_web_search_settings(db)
    if settings.duckduckgo_fallback and not any(step.target.provider == DUCKDUCKGO for step in steps):
        steps.append(
            SearchStep(target=SearchTarget(provider=DUCKDUCKGO), label="DuckDuckGo", connection_id=None, price_usd=0.0)
        )
    return steps


#: Why Web Search is off, as the chat's tool menu says it.
NOT_CONFIGURED_MESSAGE = "No web search service is set up: an administrator adds one under Connections → Web search."


async def web_search_availability(db: AsyncSession) -> str | None:
    """None when a search has a service to ask; otherwise why not, for the tool menu."""
    return None if await search_plan(db) else NOT_CONFIGURED_MESSAGE


@dataclass(frozen=True)
class SearchFailure:
    label: str
    code: str
    message: str


@dataclass
class WebSearchOutcome:
    results: list[SearchResult]
    #: The service that answered.
    label: str
    failures: list[SearchFailure] = field(default_factory=list)


class WebSearchUnavailable(Exception):
    """No service answered: each one's reason, the first being the most telling (the primary's)."""

    def __init__(self, failures: list[SearchFailure]) -> None:
        self.failures = failures
        message = "; ".join(f"{f.label}: {f.message}" for f in failures[:3]) if failures else NOT_CONFIGURED_MESSAGE
        super().__init__(message)
        self.message = message
        self.code = failures[0].code if failures else ERROR_NOT_CONFIGURED


async def search_web(
    query: str,
    limit: int,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    username: str | None = None,
    reserve_budget: bool = True,
    session_factory: Callable[[], Any] | None = None,
    provider_options: dict[str, Any] | None = None,
) -> WebSearchOutcome:
    """Ask the services in order until one answers; raises WebSearchUnavailable with every reason."""
    from app.database import AsyncSessionLocal

    async with (session_factory or AsyncSessionLocal)() as db:
        steps = await search_plan(db)
    failures: list[SearchFailure] = []
    metering = user_id is not None or alpha_router_api_key_id is not None
    for step in steps:
        metered = (
            await start_metered_usage(
                user_id=user_id,
                alpha_router_api_key_id=alpha_router_api_key_id,
                username=username,
                provider_type=step.target.provider,
                service_type="web_search",
                operation_name="web_search",
                model_id=f"{step.target.provider}-search",
                connection_id=step.connection_id,
                metadata={"connection": step.label, "max_results": limit},
                reserve_budget=reserve_budget,
            )
            if metering
            else None
        )
        try:
            results = await run_search(step.target, query, limit, **(provider_options or {}))
        except WebSearchError as exc:
            failures.append(SearchFailure(label=step.label, code=exc.code, message=exc.message))
            if metered is not None:
                await finish_metered_usage(metered, success=False, quantity=None, unit=None, error_message=exc.message)
            logger.info("Web search via %s failed: %s", step.target.provider, exc.code)
            continue
        except BaseException as exc:
            if metered is not None:
                await finish_metered_usage(
                    metered, success=False, quantity=None, unit=None, error_message=str(exc) or type(exc).__name__
                )
            raise
        if metered is not None:
            await finish_metered_usage(
                metered,
                response={"usage": {"total_cost_usd": step.price_usd}} if step.price_usd > 0 else None,
                success=True,
                quantity=1,
                unit="request",
            )
        return WebSearchOutcome(results=results, label=step.label, failures=failures)
    raise WebSearchUnavailable(failures)
