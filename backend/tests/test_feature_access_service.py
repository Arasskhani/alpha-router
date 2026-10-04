"""Who may use the web Chat and Projects.

The order an administrator is promised: an admin always may; a rule on the
person decides; otherwise a deny on a group or the department does; otherwise
the section is open. Each step is pinned here, and so is the fact that a
deployment with no rules pays for none of it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.feature_access import FeatureAccessRule
from app.models.user import UserGroup, user_group_members
from app.services.feature_access_service import (
    FEATURE_FORBIDDEN_CODE,
    REASON_ADMIN,
    REASON_DEFAULT,
    REASON_DEPARTMENT_DENY,
    REASON_GROUP_DENY,
    REASON_USER_ALLOW,
    REASON_USER_DENY,
    decide,
    decide_all,
    feature_enabled_for_user_id,
    require_feature,
)


async def _group(db, name: str, *user_ids: int) -> UserGroup:
    group = UserGroup(name=name)
    db.add(group)
    await db.flush()
    for user_id in user_ids:
        await db.execute(user_group_members.insert().values(group_id=group.id, user_id=user_id))
    await db.commit()
    return group


async def _rule(db, feature: str, effect: str = "deny", **target) -> FeatureAccessRule:
    rule = FeatureAccessRule(feature=feature, effect=effect, **target)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


class TestWithNoRules:
    async def test_everyone_may_use_both_sections(self, db_session, user):
        decisions = await decide_all(db_session, user)
        assert {key: d.allowed for key, d in decisions.items()} == {"chat": True, "projects": True}
        assert all(d.reason == REASON_DEFAULT for d in decisions.values())

    async def test_reads_no_roles(self, db_session, user, monkeypatch):
        """The common case is one query: no rules, no role lookup."""
        import app.services.feature_access_service as svc

        async def boom(*_a, **_k):
            raise AssertionError("roles were read with no rules saved")

        monkeypatch.setattr(svc, "get_user_role_slugs", boom)
        assert (await decide(db_session, user, "chat")).allowed


class TestDeny:
    async def test_a_user_rule_closes_the_section_for_that_person_only(self, db_session, user, admin):
        rule = await _rule(db_session, "chat", user_id=user.id)
        decision = await decide(db_session, user, "chat")
        assert not decision.allowed
        assert decision.reason == REASON_USER_DENY
        assert decision.rule_id == rule.id
        assert (await decide(db_session, user, "projects")).allowed

    async def test_a_group_rule_closes_it_for_members(self, db_session, user):
        group = await _group(db_session, "Interns", user.id)
        await _rule(db_session, "projects", group_id=group.id)
        decision = await decide(db_session, user, "projects")
        assert not decision.allowed
        assert decision.reason == REASON_GROUP_DENY
        assert decision.via == "Interns"

    async def test_a_group_rule_leaves_non_members_alone(self, db_session, user):
        group = await _group(db_session, "Elsewhere")
        await _rule(db_session, "projects", group_id=group.id)
        assert (await decide(db_session, user, "projects")).allowed

    async def test_a_department_rule_matches_whatever_the_case_and_spacing(self, db_session, user):
        user.department = "  Sales   Team "
        await db_session.commit()
        await _rule(db_session, "chat", department="sales team")
        decision = await decide(db_session, user, "chat")
        assert not decision.allowed
        assert decision.reason == REASON_DEPARTMENT_DENY
        assert decision.via == "sales team"

    async def test_no_department_matches_no_department_rule(self, db_session, user):
        await _rule(db_session, "chat", department="Sales")
        assert (await decide(db_session, user, "chat")).allowed


class TestPrecedence:
    async def test_a_user_allow_beats_a_group_deny(self, db_session, user):
        group = await _group(db_session, "Contractors", user.id)
        await _rule(db_session, "chat", group_id=group.id)
        await _rule(db_session, "chat", effect="allow", user_id=user.id)
        decision = await decide(db_session, user, "chat")
        assert decision.allowed
        assert decision.reason == REASON_USER_ALLOW

    async def test_a_user_allow_beats_a_department_deny(self, db_session, user):
        user.department = "Finance"
        await db_session.commit()
        await _rule(db_session, "projects", department="Finance")
        await _rule(db_session, "projects", effect="allow", user_id=user.id)
        assert (await decide(db_session, user, "projects")).allowed

    async def test_a_deny_on_any_group_wins_over_the_others(self, db_session, user):
        await _group(db_session, "Open", user.id)
        closed = await _group(db_session, "Closed", user.id)
        await _rule(db_session, "chat", group_id=closed.id)
        assert not (await decide(db_session, user, "chat")).allowed

    async def test_an_admin_always_may(self, db_session, admin):
        await _rule(db_session, "chat", user_id=admin.id)
        await _rule(db_session, "projects", user_id=admin.id)
        decisions = await decide_all(db_session, admin)
        assert all(d.allowed and d.reason == REASON_ADMIN for d in decisions.values())


class TestTheTable:
    async def test_one_rule_per_feature_and_person(self, db_session, user):
        await _rule(db_session, "chat", user_id=user.id)
        db_session.add(FeatureAccessRule(feature="chat", effect="allow", user_id=user.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_allow_is_for_a_person_only(self, db_session, user):
        group = await _group(db_session, "G")
        db_session.add(FeatureAccessRule(feature="chat", effect="allow", group_id=group.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_exactly_one_target(self, db_session, user):
        db_session.add(FeatureAccessRule(feature="chat", effect="deny", user_id=user.id, department="X"))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_only_known_features(self, db_session, user):
        db_session.add(FeatureAccessRule(feature="images", effect="deny", user_id=user.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()


class TestHelpers:
    async def test_require_feature_refuses_with_a_code_the_client_reads(self, db_session, user):
        await _rule(db_session, "projects", user_id=user.id)
        with pytest.raises(HTTPException) as caught:
            await require_feature(db_session, user, "projects")
        assert caught.value.status_code == 403
        assert caught.value.detail["code"] == FEATURE_FORBIDDEN_CODE
        assert caught.value.detail["feature"] == "projects"
        await require_feature(db_session, user, "chat")

    async def test_by_id_for_background_work(self, db_session, user):
        await _rule(db_session, "chat", user_id=user.id)
        assert not await feature_enabled_for_user_id(db_session, int(user.id), "chat")
        assert await feature_enabled_for_user_id(db_session, int(user.id), "projects")
        assert not await feature_enabled_for_user_id(db_session, 999_999, "projects")

    async def test_an_unknown_feature_is_not_found(self, db_session, user):
        with pytest.raises(HTTPException) as caught:
            await decide(db_session, user, "spreadsheets")
        assert caught.value.status_code == 404
