"""Admin: Guardrails - patterns, rules, scope, destinations, settings, Test a text, events and the overview."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.connection import Connection
from app.models.guardrail import GuardrailEvent, GuardrailRule
from app.models.security import SecurityAuditEvent
from app.services.guardrail_policy import load_policy
from app.services.secret_crypto import encrypt_secret

CSRF = "csrf-token"
BASE = "/api/admin/guardrails"
CARD = "6037991899123453"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


CONTRACT = {
    "name": "Contract number",
    "kind": "regex",
    "expression": r"\bCNT-\d{4}-\d{5}\b",
    "context_words": ["قرارداد", "contract"],
    "context_window": 50,
    "redact_label": "CONTRACT",
    "must_match": ["قرارداد CNT-2025-10442"],
    "must_not_match": ["CNT-12-3"],
}


def rule_body(**fields):
    body = {
        "name": "Cards to public models",
        "mode": "enforce",
        "patterns": ["lib:bank_card"],
        "channels": ["chat", "attachments"],
        "destinations": ["public"],
        "action": "redact",
        "user_message": "Cards were masked.",
    }
    body.update(fields)
    return body


async def audits(db, action: str) -> list[SecurityAuditEvent]:
    return list(
        (await db.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == action))).scalars().all()
    )


class TestAccess:
    async def test_a_plain_user_reaches_none_of_it(self, client, user):
        headers = sign_in(client, user)
        for path in ("/meta", "/rules", "/patterns", "/events", "/overview", "/settings", "/destinations"):
            assert (await client.get(BASE + path, headers=headers)).status_code == 403, path
        assert (await client.post(f"{BASE}/rules", json=rule_body(), headers=headers)).status_code == 403

    async def test_nothing_exists_until_an_administrator_writes_it(self, client, admin):
        headers = sign_in(client, admin)
        assert (await client.get(f"{BASE}/rules", headers=headers)).json() == []
        patterns = (await client.get(f"{BASE}/patterns", headers=headers)).json()
        assert patterns["custom"] == [] and len(patterns["library"]) >= 10
        assert (await client.get(f"{BASE}/overview", headers=headers)).json()["rules"] == {
            "off": 0,
            "monitor": 0,
            "enforce": 0,
        }


class TestPatterns:
    async def test_create_test_update_export_import_and_delete(self, client, db_session, admin):
        headers = sign_in(client, admin)
        resp = await client.post(f"{BASE}/patterns", json=CONTRACT, headers=headers)
        assert resp.status_code == 200, resp.text
        pattern = resp.json()
        assert pattern["ref"] == f"custom:{pattern['id']}"
        tried = await client.post(
            f"{BASE}/patterns/test",
            json={"pattern": CONTRACT, "text": "لطفا قرارداد CNT-2025-10442 را با CNT-12-3 مقایسه کن"},
            headers=headers,
        )
        assert tried.json()["matches"] == [{"start": 13, "end": 27, "value": "CNT-2025-10442"}]
        resp = await client.put(
            f"{BASE}/patterns/{pattern['id']}", json={**CONTRACT, "name": "Contract"}, headers=headers
        )
        assert resp.json()["version"] == 2
        exported = (await client.get(f"{BASE}/patterns/export", headers=headers)).json()
        assert exported["patterns"][0]["name"] == "Contract"
        assert (await client.post(f"{BASE}/patterns/import", json=exported, headers=headers)).json() == {"imported": 1}
        assert (await client.delete(f"{BASE}/patterns/{pattern['id']}", headers=headers)).status_code == 200
        assert [a.resource_id for a in await audits(db_session, "guardrail_pattern_created")] == [str(pattern["id"])]

    @pytest.mark.parametrize(
        ("change", "reason"),
        [
            ({"expression": "(a+)+$\\1"}, "Not a valid expression"),
            ({"expression": ".*"}, "empty text"),
            ({"must_match": ["no match here"]}, "samples wrong"),
            ({"redact_label": "lower case"}, "redaction label"),
        ],
    )
    async def test_a_pattern_that_cannot_be_used_is_refused_with_the_reason(self, client, admin, change, reason):
        headers = sign_in(client, admin)
        resp = await client.post(f"{BASE}/patterns", json={**CONTRACT, **change}, headers=headers)
        assert resp.status_code == 400 and reason in resp.json()["detail"]

    async def test_the_live_test_says_why_a_draft_cannot_be_used(self, client, admin):
        headers = sign_in(client, admin)
        resp = await client.post(
            f"{BASE}/patterns/test", json={"pattern": {**CONTRACT, "expression": "(?=x)"}, "text": "x"}, headers=headers
        )
        assert resp.json()["ok"] is False and "Not a valid expression" in resp.json()["error"]

    async def test_a_pattern_in_use_cannot_be_deleted(self, client, admin):
        headers = sign_in(client, admin)
        pattern = (await client.post(f"{BASE}/patterns", json=CONTRACT, headers=headers)).json()
        await client.post(f"{BASE}/rules", json=rule_body(patterns=[pattern["ref"]]), headers=headers)
        resp = await client.delete(f"{BASE}/patterns/{pattern['id']}", headers=headers)
        assert resp.status_code == 409 and "Cards to public models" in resp.json()["detail"]


class TestRules:
    async def test_create_list_change_mode_move_and_delete(self, client, db_session, admin):
        headers = sign_in(client, admin)
        first = (await client.post(f"{BASE}/rules", json=rule_body(), headers=headers)).json()
        second = (await client.post(f"{BASE}/rules", json=rule_body(name="Keys", patterns=["lib:openai_key"], action="block"), headers=headers)).json()  # fmt: skip
        assert first["pattern_names"] == ["Bank card"] and first["access_type"] == "public"
        assert [r["name"] for r in (await client.get(f"{BASE}/rules", headers=headers)).json()] == ["Cards to public models", "Keys"]  # fmt: skip
        moved = (
            await client.post(f"{BASE}/rules/{second['id']}/move", json={"direction": "up"}, headers=headers)
        ).json()
        assert [r["name"] for r in moved] == ["Keys", "Cards to public models"]
        resp = await client.patch(f"{BASE}/rules/{first['id']}/mode", json={"mode": "monitor"}, headers=headers)
        assert resp.json()["mode"] == "monitor" and resp.json()["version"] == 2
        policy = await load_policy(db_session)
        assert [r.name for r in policy.rules] == ["Keys", "Cards to public models"]
        assert (await client.delete(f"{BASE}/rules/{first['id']}", headers=headers)).status_code == 200
        for action in ("guardrail_rule_created", "guardrail_rules_reordered", "guardrail_rule_mode_changed", "guardrail_rule_deleted"):  # fmt: skip
            assert await audits(db_session, action), action

    @pytest.mark.parametrize(
        ("change", "reason"),
        [
            ({"patterns": ["lib:nope"]}, "Unknown pattern"),
            ({"channels": ["email"]}, "Channels are"),
            ({"destinations": ["friendly"]}, "trust levels"),
            ({"action": "route"}, "Choose the model"),
            ({"action": "route", "channels": ["web_search"], "route_model_id": 1}, "routed"),
            ({"action": "redact", "channels": ["web_fetch"]}, "cannot be masked"),
        ],
    )
    async def test_a_rule_that_cannot_work_is_refused(self, client, admin, change, reason):
        headers = sign_in(client, admin)
        resp = await client.post(f"{BASE}/rules", json=rule_body(**change), headers=headers)
        assert resp.status_code == 400 and reason in resp.json()["detail"], resp.text

    async def test_route_to_an_enabled_model(self, client, db_session, admin):
        from tests.test_extension_browser_tools import _model

        model = await _model(db_session, "llama-internal")
        headers = sign_in(client, admin)
        resp = await client.post(
            f"{BASE}/rules", json=rule_body(action="route", route_model_id=model.id), headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["route_model_label"].startswith("Model llama-internal")

    async def test_who_it_applies_to(self, client, db_session, admin, user):
        headers = sign_in(client, admin)
        created = (await client.post(f"{BASE}/rules", json=rule_body(), headers=headers)).json()
        url = f"{BASE}/rules/{created['id']}/access"
        current = (await client.get(url, headers=headers)).json()
        assert current == {**current, "access_type": "public", "grants": []}
        body = {
            "access_type": "public",
            "grants": [{"target_type": "user", "target": user.id, "effect": "deny"}],
            "acl_version": current["acl_version"],
        }
        saved = await client.put(url, json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["grants"] == [{"target_type": "user", "target": user.id, "effect": "deny"}]
        stale = await client.put(url, json=body, headers=headers)
        assert stale.status_code == 409
        listed = (await client.get(f"{BASE}/rules", headers=headers)).json()[0]
        assert listed["deny_count"] == 1


class TestDestinationsAndSettings:
    async def test_trust_levels(self, client, db_session, admin):
        headers = sign_in(client, admin)
        conn = Connection(name="Ollama", kind="models", provider_type="ollama", api_key_encrypted=encrypt_secret(""))
        db_session.add(conn)
        await db_session.commit()
        listed = (await client.get(f"{BASE}/destinations", headers=headers)).json()
        assert listed["connections"][0]["trust_level"] == "public"
        assert {d["key"] for d in listed["implicit"]} == {"duckduckgo", "web_fetch"}
        resp = await client.put(f"{BASE}/destinations/{conn.id}", json={"trust_level": "internal"}, headers=headers)
        assert resp.status_code == 200
        await db_session.refresh(conn)
        assert conn.trust_level == "internal"
        assert await audits(db_session, "guardrail_destination_trust_changed")

    async def test_settings(self, client, admin):
        headers = sign_in(client, admin)
        assert (await client.get(f"{BASE}/settings", headers=headers)).json() == {
            "fail_closed": True,
            "restore_replies": True,
            "event_retention_days": 180,
            "alert_emails": [],
        }
        resp = await client.put(
            f"{BASE}/settings",
            json={
                "fail_closed": False,
                "restore_replies": False,
                "event_retention_days": 30,
                "alert_emails": ["sec@x.io"],
            },
            headers=headers,
        )
        assert resp.json()["alert_emails"] == ["sec@x.io"]
        bad = await client.put(f"{BASE}/settings", json={"alert_emails": ["not an address"]}, headers=headers)
        assert bad.status_code == 400


class TestTryingAText:
    async def test_what_the_rules_would_do_without_recording_it(self, client, db_session, admin):
        headers = sign_in(client, admin)
        await client.post(f"{BASE}/rules", json=rule_body(), headers=headers)
        await client.post(
            f"{BASE}/rules",
            json=rule_body(
                name="Keys", patterns=["lib:openai_key"], action="block", mode="monitor", user_message="No keys."
            ),
            headers=headers,
        )
        resp = await client.post(f"{BASE}/test", json={"text": f"card {CARD}", "channel": "chat"}, headers=headers)
        data = resp.json()
        assert data["action"] == "redact" and data["masked"] == "card [CARD_1]"
        assert data["rules"][0]["matches"] == [{"start": 5, "end": 21, "value": CARD, "pattern": "lib:bank_card"}]
        key = await client.post(
            f"{BASE}/test", json={"text": "sk-proj-abcdefghijklmnopqrstuvwxyz0123", "channel": "chat"}, headers=headers
        )
        # A monitored rule is tried as if it enforced, and said to be monitored.
        assert key.json()["action"] == "block" and key.json()["rules"][0]["mode"] == "monitor"
        internal = await client.post(
            f"{BASE}/test", json={"text": CARD, "channel": "chat", "trust_level": "internal"}, headers=headers
        )
        assert internal.json()["action"] is None
        assert (await db_session.execute(select(GuardrailEvent))).first() is None


class TestEventsAndOverview:
    async def test_list_filter_export_and_count(self, client, db_session, admin):
        headers = sign_in(client, admin)
        rule = (await client.post(f"{BASE}/rules", json=rule_body(), headers=headers)).json()
        for action, channel in (
            ("redact", "chat"),
            ("redact", "attachments"),
            ("block", "chat"),
            ("monitor", "gateway"),
        ):
            db_session.add(
                GuardrailEvent(
                    rule_id=rule["id"],
                    rule_name=rule["name"],
                    action=action,
                    channel=channel,
                    username="sara",
                    match_count=1,
                    findings_json='[{"ref": "lib:bank_card", "name": "Bank card", "count": 1, "hints": ["603…453"]}]',
                )  # fmt: skip
            )
        await db_session.commit()
        page = (await client.get(f"{BASE}/events?action=redact", headers=headers)).json()
        assert page["total"] == 2 and page["items"][0]["findings"][0]["hints"] == ["603…453"]
        assert (await client.get(f"{BASE}/events?username=SA", headers=headers)).json()["total"] == 4
        csv = await client.get(f"{BASE}/events/export.csv", headers=headers)
        assert csv.status_code == 200 and "Bank card ×1" in csv.text and CARD not in csv.text
        overview = (await client.get(f"{BASE}/overview", headers=headers)).json()
        assert overview["totals_7d"]["redact"] == 2 and overview["totals_7d"]["block"] == 1
        assert overview["rules"]["enforce"] == 1
        assert overview["top_rules"][0]["count"] == 4
        assert len(overview["daily"]) == 30 and sum(d["redact"] for d in overview["daily"]) == 2
        patterns = (await client.get(f"{BASE}/patterns", headers=headers)).json()
        card = next(p for p in patterns["library"] if p["ref"] == "lib:bank_card")
        assert card["hits_7d"] == 4 and card["used_by"] == ["Cards to public models"]
        assert (await client.get(f"{BASE}/rules", headers=headers)).json()[0]["hits_7d"] == 4
        assert await audits(db_session, "guardrail_events_exported")
        assert (await db_session.execute(select(GuardrailRule))).scalars().first() is not None
