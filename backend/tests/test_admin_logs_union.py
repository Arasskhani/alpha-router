"""Admin Logs shows every administrative trail, not only the security one.

The product writes eight audit tables - security settings, agents, tools,
knowledge, governance, projects, API keys and provider connections - and the
Admin Logs page read one. Phase 5 chose to *say so* in the Admin Guide rather
than build the union; that was the cheaper option and the plan's own lean was
the other one. This is the other one.

Each source keeps its own table (the governance chain in particular must not
be touched), and the page reads a normalised union: source, time, actor,
action, resource, detail. The default source is still ``security`` so nothing
that called the endpoint before changes; the page asks for ``all``.
"""

from __future__ import annotations

import datetime
import uuid

from app.api.admin_logs import admin_log_filter_options, list_admin_logs
from app.core.security import hash_password
from app.models.agent import AgentAuditEvent
from app.models.agent_tool import AgentToolAuditEvent
from app.models.api_key import AlphaRouterApiKey, AlphaRouterApiKeyAuditLog
from app.models.auth_event import AuthEvent
from app.models.connection import Connection, ConnectionAuditLog
from app.models.governance import GovernanceAuditEvent
from app.models.knowledge import KnowledgeAuditEvent
from app.models.project import ProjectAuditEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User


def _at(minutes: int) -> datetime.datetime:
    return datetime.datetime(2026, 9, 19, 12, minutes, 0)


async def _seed(db_session) -> User:
    actor = User(
        username="auditor",
        email="auditor@test",
        hashed_password=hash_password("x"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(actor)
    await db_session.flush()
    key = AlphaRouterApiKey(name="svc", key_prefix="ar_abc", key_hash="h" * 64, owner_user_id=actor.id)
    conn = Connection(name="openai-main", provider_type="openai", api_key_encrypted="enc")
    db_session.add_all([key, conn])
    await db_session.flush()
    db_session.add_all(
        [
            SecurityAuditEvent(
                actor_user_id=actor.id,
                actor_username="auditor",
                action="tls_activate",
                resource_type="tls",
                created_at=_at(1),
            ),
            AgentAuditEvent(
                id=str(uuid.uuid4()),
                actor_user_id=actor.id,
                event_type="agent.version.published",
                payload={"version": 3},
                created_at=_at(2),
            ),
            AgentToolAuditEvent(
                id=str(uuid.uuid4()),
                actor_user_id=actor.id,
                event_type="tool.version.approved",
                payload={},
                created_at=_at(3),
            ),
            KnowledgeAuditEvent(
                id=str(uuid.uuid4()),
                actor_user_id=actor.id,
                event_type="document.version.approved",
                payload_json={"maker_checker": "two_person"},
                created_at=_at(4),
            ),
            GovernanceAuditEvent(
                id=str(uuid.uuid4()),
                actor_user_id=actor.id,
                event_type="legal_hold.placed",
                resource_type="agent",
                resource_id="a-1",
                outcome="success",
                payload_json={},
                previous_event_hash=None,
                event_hash="e" * 64,
                created_at=_at(5),
            ),
            ProjectAuditEvent(
                id=str(uuid.uuid4()),
                actor_user_id=actor.id,
                project_id="p-1",
                event_type="project.deleted",
                payload_json={},
                created_at=_at(6),
            ),
            AlphaRouterApiKeyAuditLog(
                alpha_router_api_key_id=key.id,
                actor_user_id=actor.id,
                action="revoked",
                changes_json="[]",
                created_at=_at(7),
            ),
            ConnectionAuditLog(
                connection_id=conn.id,
                actor_user_id=actor.id,
                action="updated",
                changes_json='[{"field":"model"}]',
                created_at=_at(8),
            ),
            AuthEvent(
                occurred_at=_at(9),
                user_id=actor.id,
                username="auditor",
                event_type="login_failed",
                outcome="failure",
                reason_code="bad_password",
                reason_detail='Provider said "no"',
                auth_method="ldap",
                ip="203.0.113.7",
                session_id=None,
            ),
        ]
    )
    await db_session.commit()
    return actor


def _args(db, **overrides):
    base = {
        "db": db,
        "_": None,
        "limit": 100,
        "offset": 0,
        "actor": None,
        "action": None,
        "resource_type": None,
        "start_date": None,
        "end_date": None,
        "source": "all",
    }
    base.update(overrides)
    return base


async def test_all_nine_trails_appear_in_one_list_newest_first(db_session):
    await _seed(db_session)

    result = await list_admin_logs(**_args(db_session))

    sources = [row["source"] for row in result["items"]]
    assert sources == [
        "authentication",
        "connections",
        "api_keys",
        "projects",
        "governance",
        "knowledge",
        "tools",
        "agents",
        "security",
    ]
    actions = [row["action"] for row in result["items"]]
    assert actions[0] == "login_failed" and actions[-1] == "tls_activate"


async def test_every_row_names_its_actor_even_where_the_table_stores_only_an_id(db_session):
    await _seed(db_session)

    result = await list_admin_logs(**_args(db_session))

    assert {row["actor_username"] for row in result["items"]} == {"auditor"}
    # The security and sign-in trails store a copy of the name; the rest name only an id.
    assert all(
        row["actor_resolved_live"] is (row["source"] not in ("security", "authentication")) for row in result["items"]
    )


async def test_the_actor_filter_reaches_every_trail(db_session):
    await _seed(db_session)
    result = await list_admin_logs(**_args(db_session, actor="audit"))
    assert len(result["items"]) == 9
    none = await list_admin_logs(**_args(db_session, actor="somebody-else"))
    assert none["items"] == []


async def test_a_single_source_can_be_asked_for(db_session):
    await _seed(db_session)
    only = await list_admin_logs(**_args(db_session, source="knowledge"))
    assert [row["source"] for row in only["items"]] == ["knowledge"]
    assert only["items"][0]["detail"] == {"maker_checker": "two_person"}


async def test_the_default_source_is_still_the_security_trail(db_session):
    """Callers that never heard of `source` see exactly what they saw before."""
    await _seed(db_session)
    result = await list_admin_logs(**_args(db_session, source=None))
    assert [row["source"] for row in result["items"]] == ["security"]


async def test_paging_across_sources_neither_repeats_nor_skips(db_session):
    await _seed(db_session)
    seen: list[str] = []
    for offset in (0, 3, 6):
        page = await list_admin_logs(**_args(db_session, limit=3, offset=offset))
        seen.extend(f"{row['source']}:{row['id']}" for row in page["items"])
        assert page["has_more"] is (offset < 6)
    assert len(seen) == 9 and len(set(seen)) == 9


async def test_the_resource_type_is_the_kind_of_thing_each_trail_is_about(db_session):
    await _seed(db_session)
    result = await list_admin_logs(**_args(db_session))
    by_source = {row["source"]: row for row in result["items"]}
    assert by_source["agents"]["resource_type"] == "agent"
    assert by_source["api_keys"]["resource_type"] == "api_key"
    assert by_source["connections"]["resource_type"] == "connection"
    assert by_source["projects"]["resource_id"] == "p-1"
    assert by_source["governance"]["resource_type"] == "agent"


async def test_the_date_range_applies_to_the_union(db_session):
    await _seed(db_session)
    result = await list_admin_logs(**_args(db_session, start_date="2026-09-19", end_date="2026-09-19"))
    assert len(result["items"]) == 9
    none = await list_admin_logs(**_args(db_session, start_date="2026-09-20"))
    assert none["items"] == []


async def test_filter_options_cover_every_trail_when_asked_for_all(db_session):
    await _seed(db_session)
    from app.api import admin_logs

    admin_logs.reset_filter_options_cache()
    options = await admin_log_filter_options(db=db_session, _=None, source="all")
    assert "agent.version.published" in options["actions"]
    assert "tls_activate" in options["actions"]
    assert "connection" in options["resource_types"]
    assert options["actors"] == ["auditor"]
    assert set(options["sources"]) >= {"security", "agents", "knowledge", "governance"}


async def test_sign_ins_are_still_in_the_trail_after_moving_tables(db_session):
    """Before ``auth_events`` existed, sign-ins were security rows with
    ``resource_type='authentication'``. The move must not make them vanish
    from this page: same resource type, the account as the actor, the typed
    columns folded into the detail — with a quote in the provider message
    escaped by the database, not by string concatenation."""
    await _seed(db_session)

    only = await list_admin_logs(**_args(db_session, source="authentication"))
    assert len(only["items"]) == 1
    row = only["items"][0]
    assert row["source"] == "authentication"
    assert row["action"] == "login_failed"
    assert row["outcome"] == "failure"
    assert row["resource_type"] == "authentication"
    assert row["actor_username"] == "auditor"
    assert row["actor_ip"] == "203.0.113.7"
    assert row["actor_resolved_live"] is False
    assert row["detail"]["reason_code"] == "bad_password"
    assert row["detail"]["reason_detail"] == 'Provider said "no"'
    assert row["detail"]["auth_method"] == "ldap"
    assert not row["detail"]["backfilled"]

    by_type = await list_admin_logs(**_args(db_session, resource_type="authentication"))
    assert [r["source"] for r in by_type["items"]] == ["authentication"]


async def test_the_filter_panel_offers_sign_in_actions_and_the_account(db_session):
    await _seed(db_session)
    options = await admin_log_filter_options(db=db_session, _=None, source="authentication")
    assert options["actions"] == ["login_failed"]
    assert options["resource_types"] == ["authentication"]
    assert options["actors"] == ["auditor"]
