"""Two reports for what automatic memory spends.

Extraction is billed as a system operation and never charged to a user's
plan, so it is absent from every screen that answers "why is this person
expensive". These put it back, from the two directions an operator asks: who
is it being spent on, and what is it costing the organization day by day.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logging import RequestLog
from app.models.project import Project
from app.models.user import User
from app.services.reports_service import build_report
from app.utils.display import MEMORY_USAGE_SOURCE

START = dt.datetime(2026, 9, 1)
END = dt.datetime(2026, 9, 30)


def _log(
    *,
    user_id: int | None,
    username: str,
    cost: float,
    source: str = MEMORY_USAGE_SOURCE,
    day: int = 10,
    project_id: str | None = None,
    prompt: int = 1000,
    completion: int = 50,
) -> RequestLog:
    return RequestLog(
        user_id=user_id,
        username=username,
        model_id="gpt-extract",
        source=source,
        client_app="Memory" if source == MEMORY_USAGE_SOURCE else "Alpharouter Chat",
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=0,
        total_cost_usd=cost,
        project_id=project_id,
        request_time=dt.datetime(2026, 9, day, 12, 0, 0),
        success=True,
    )


@pytest.fixture
async def people(db_session: AsyncSession) -> dict[str, int]:
    ids = {}
    for name in ("ada", "linus"):
        row = User(username=name, email=f"{name}@x", hashed_password="x", auth_provider="local")
        db_session.add(row)
        await db_session.flush()
        ids[name] = row.id
    await db_session.commit()
    return ids


async def _run(db: AsyncSession, report: str, **params):
    return await build_report(db, report, {"_start": START, "_end": END, **params})


async def test_by_user_counts_only_extraction_rows(db_session, people) -> None:
    db_session.add_all(
        [
            _log(user_id=people["ada"], username="ada", cost=1.00),
            _log(user_id=people["ada"], username="ada", cost=0.50),
            _log(user_id=people["ada"], username="ada", cost=8.50, source="alpha_router_chat"),
            _log(user_id=people["linus"], username="linus", cost=0.50),
        ]
    )
    await db_session.commit()

    df = await _run(db_session, "memory_cost_by_user")
    by_name = {row["username"]: row for row in df.to_dict("records")}
    assert by_name["ada"]["cost_usd"] == 1.50
    assert by_name["ada"]["extractions"] == 2
    # 1.50 of 10.00 total for ada; 1.50 of 2.00 spent on memory overall.
    assert by_name["ada"]["pct_of_their_spend"] == 15.0
    assert by_name["ada"]["pct_of_memory_spend"] == 75.0


async def test_by_user_ranks_by_cost_and_honours_top_n(db_session, people) -> None:
    db_session.add_all(
        [
            _log(user_id=people["ada"], username="ada", cost=0.10),
            _log(user_id=people["linus"], username="linus", cost=2.00),
        ]
    )
    await db_session.commit()

    df = await _run(db_session, "memory_cost_by_user", top_n=1)
    assert [row["username"] for row in df.to_dict("records")] == ["linus"]


async def test_by_user_can_be_narrowed_to_one_person(db_session, people) -> None:
    db_session.add_all(
        [
            _log(user_id=people["ada"], username="ada", cost=1.00),
            _log(user_id=people["linus"], username="linus", cost=2.00),
        ]
    )
    await db_session.commit()

    df = await _run(db_session, "memory_cost_by_user", user_id=people["ada"])
    assert [row["username"] for row in df.to_dict("records")] == ["ada"]


async def test_by_user_is_empty_rather_than_broken_when_nothing_ran(db_session, people) -> None:
    db_session.add(_log(user_id=people["ada"], username="ada", cost=5.0, source="alpha_router_chat"))
    await db_session.commit()
    assert (await _run(db_session, "memory_cost_by_user")).empty


async def test_summary_splits_personal_from_project(db_session, people) -> None:
    db_session.add(Project(id="proj-1", name="Billing"))
    await db_session.flush()
    db_session.add_all(
        [
            _log(user_id=people["ada"], username="ada", cost=1.00, day=10),
            _log(user_id=None, username="platform", cost=0.40, day=10, project_id="proj-1"),
            _log(user_id=people["ada"], username="ada", cost=9.00, day=10, source="alpha_router_chat"),
            _log(user_id=people["ada"], username="ada", cost=0.25, day=11),
        ]
    )
    await db_session.commit()

    rows = (await _run(db_session, "memory_cost_summary")).to_dict("records")
    first = rows[0]
    assert first["date"].startswith("2026-09-10")
    assert first["personal_usd"] == 1.00
    assert first["project_usd"] == 0.40
    assert first["total_usd"] == 1.40
    # 1.40 of 10.40 spent that day.
    assert first["pct_of_org_spend"] == 13.46
    assert [row["date"].startswith("2026-09-11") for row in rows][1] is True


async def test_summary_ignores_days_outside_the_window(db_session, people) -> None:
    db_session.add_all(
        [
            _log(user_id=people["ada"], username="ada", cost=1.00, day=10),
            RequestLog(
                user_id=people["ada"],
                username="ada",
                model_id="gpt-extract",
                source=MEMORY_USAGE_SOURCE,
                total_cost_usd=99.0,
                prompt_tokens=1,
                completion_tokens=1,
                cached_tokens=0,
                request_time=dt.datetime(2026, 8, 10),
                success=True,
            ),
        ]
    )
    await db_session.commit()

    rows = (await _run(db_session, "memory_cost_summary")).to_dict("records")
    assert len(rows) == 1
    assert rows[0]["total_usd"] == 1.00


async def test_both_reports_are_in_the_catalog_under_budget(db_session) -> None:
    from app.services.reports_catalog import REPORT_CATALOG

    entries = {r["id"]: r for r in REPORT_CATALOG}
    for report_id in ("memory_cost_by_user", "memory_cost_summary"):
        assert entries[report_id]["category"] == "budget"
        assert entries[report_id]["needs_date"] is True
    # Only ParamKinds the Reports page already renders, so no frontend change.
    assert set(entries["memory_cost_by_user"]["params"]) <= {"user", "top_n"}
    assert entries["memory_cost_summary"]["params"] == []
