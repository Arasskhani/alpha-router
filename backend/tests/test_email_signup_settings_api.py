"""Admin -> Authentication -> Email sign-up: the settings API."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.budget import BudgetPlan
from app.models.security import SecurityAuditEvent
from app.models.system import SmtpSettings

CSRF = "csrf-token"
PATH = "/api/admin/authentication/email-signup"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _smtp(db) -> None:
    db.add(SmtpSettings(host="smtp.example.com", port=587, from_address="noreply@example.com"))
    await db.commit()


async def test_it_starts_off_and_lists_the_plans(client, db_session, admin):
    db_session.add(BudgetPlan(name="Starter", monthly_budget_usd=5))
    await db_session.commit()
    _sign_in(client, admin)
    body = (await client.get(PATH)).json()
    assert body["enabled"] is False and body["reset_enabled"] is False
    assert body["allowed_domains"] == [] and body["default_plan_id"] is None
    assert body["smtp_configured"] is False
    assert [p["name"] for p in body["plans"]] == ["Starter"]
    assert body["signups_last_30_days"] == 0


async def test_saving_checks_and_records_it(client, db_session, admin, session_factory):
    await _smtp(db_session)
    plan = BudgetPlan(name="Starter", monthly_budget_usd=5)
    db_session.add(plan)
    await db_session.commit()
    headers = _sign_in(client, admin)
    saved = await client.put(
        PATH,
        json={
            "enabled": True,
            "allowed_domains": [" @Example.com ", "example.org", "example.com", ""],
            "default_plan_id": plan.id,
            "reset_enabled": True,
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["allowed_domains"] == ["example.com", "example.org"]
    assert body["enabled"] and body["reset_enabled"] and body["default_plan_id"] == plan.id
    async with session_factory() as fresh:
        audit = (
            await fresh.execute(
                select(SecurityAuditEvent).where(SecurityAuditEvent.action == "email_signup_settings_changed")
            )
        ).scalar_one()
        assert "example.org" in audit.detail_json
    methods = (await client.get("/api/auth/methods")).json()
    assert methods["email_signup"] and methods["password_reset"]


async def test_bad_values_are_refused(client, db_session, admin):
    headers = _sign_in(client, admin)
    no_smtp = await client.put(PATH, json={"enabled": True}, headers=headers)
    assert no_smtp.status_code == 400 and "SMTP" in no_smtp.json()["detail"]
    await _smtp(db_session)
    bad_domain = await client.put(PATH, json={"enabled": True, "allowed_domains": ["not a domain"]}, headers=headers)
    assert bad_domain.status_code == 400 and "not a domain" in bad_domain.json()["detail"]
    no_plan = await client.put(PATH, json={"enabled": True, "default_plan_id": 999}, headers=headers)
    assert no_plan.status_code == 400 and "plan" in no_plan.json()["detail"]
    # Off needs no SMTP and nothing else.
    assert (await client.put(PATH, json={"enabled": False}, headers=headers)).status_code == 200


async def test_a_plain_user_reaches_none_of_it(client, user):
    headers = _sign_in(client, user)
    assert (await client.get(PATH)).status_code == 403
    assert (await client.put(PATH, json={"enabled": False}, headers=headers)).status_code == 403
