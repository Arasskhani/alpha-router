"""Create projects: its own rules, and the two sections it closes with.

A person whose Chat is closed must not be able to create a project of their
own and chat there, so Create projects closes with Chat - unless the person
has an Allow of their own on it - and always with Projects, since a project
cannot be used without it.
"""

from __future__ import annotations

from app.models.feature_access import FeatureAccessRule
from app.models.user import UserGroup, user_group_members
from app.services.feature_access_service import (
    REASON_ADMIN,
    REASON_CHAT_CLOSED,
    REASON_DEFAULT,
    REASON_GROUP_DENY,
    REASON_PROJECTS_CLOSED,
    REASON_USER_ALLOW,
    REASON_USER_DENY,
    decide,
    decide_all,
)

CREATE = "project_create"


async def _rule(db, feature: str, effect: str = "deny", **target) -> FeatureAccessRule:
    rule = FeatureAccessRule(feature=feature, effect=effect, **target)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def _group(db, name: str, *user_ids: int) -> UserGroup:
    group = UserGroup(name=name)
    db.add(group)
    await db.flush()
    for user_id in user_ids:
        await db.execute(user_group_members.insert().values(group_id=group.id, user_id=user_id))
    await db.commit()
    return group


async def test_open_by_default(db_session, user):
    decision = await decide(db_session, user, CREATE)
    assert decision.allowed and decision.reason == REASON_DEFAULT


async def test_its_own_rules_decide_like_any_section(db_session, user):
    group = await _group(db_session, "Interns", int(user.id))
    rule = await _rule(db_session, CREATE, group_id=group.id)
    decision = await decide(db_session, user, CREATE)
    assert (decision.allowed, decision.reason, decision.rule_id, decision.via) == (
        False,
        REASON_GROUP_DENY,
        rule.id,
        "Interns",
    )
    # The other sections are untouched.
    others = await decide_all(db_session, user, ["chat", "projects"])
    assert all(d.allowed for d in others.values())


async def test_closed_chat_closes_it(db_session, user):
    chat = await _rule(db_session, "chat", department="Sales")
    user.department = "  sales "
    await db_session.commit()
    decision = await decide(db_session, user, CREATE)
    assert (decision.allowed, decision.reason, decision.rule_id, decision.via) == (
        False,
        REASON_CHAT_CLOSED,
        chat.id,
        "Sales",
    )


async def test_a_personal_allow_overrides_the_chat_link(db_session, user):
    await _rule(db_session, "chat", user_id=user.id)
    allow = await _rule(db_session, CREATE, "allow", user_id=user.id)
    decisions = await decide_all(db_session, user)
    assert not decisions["chat"].allowed
    assert decisions[CREATE].allowed and decisions[CREATE].reason == REASON_USER_ALLOW
    assert decisions[CREATE].rule_id == allow.id


async def test_a_personal_deny_is_reported_as_itself(db_session, user):
    await _rule(db_session, "chat", user_id=user.id)
    deny = await _rule(db_session, CREATE, user_id=user.id)
    decision = await decide(db_session, user, CREATE)
    assert (decision.allowed, decision.reason, decision.rule_id) == (False, REASON_USER_DENY, deny.id)


async def test_closed_projects_closes_it_whatever_its_own_rule_says(db_session, user):
    projects = await _rule(db_session, "projects", user_id=user.id)
    await _rule(db_session, CREATE, "allow", user_id=user.id)
    decision = await decide(db_session, user, CREATE)
    assert (decision.allowed, decision.reason, decision.rule_id) == (False, REASON_PROJECTS_CLOSED, projects.id)


async def test_open_chat_and_projects_leave_it_to_its_own_rules(db_session, user):
    await _rule(db_session, "chat", "allow", user_id=user.id)
    assert (await decide(db_session, user, CREATE)).allowed


async def test_an_administrator_always_may(db_session, admin):
    await _rule(db_session, "chat", user_id=admin.id)
    await _rule(db_session, "projects", user_id=admin.id)
    decision = await decide(db_session, admin, CREATE)
    assert decision.allowed and decision.reason == REASON_ADMIN


async def test_asking_for_it_alone_returns_it_alone(db_session, user):
    await _rule(db_session, "chat", user_id=user.id)
    assert set(await decide_all(db_session, user, [CREATE])) == {CREATE}


async def test_the_extension_section_is_independent_of_chat(db_session, user):
    await _rule(db_session, "chat", user_id=user.id)
    assert (await decide(db_session, user, "extension")).allowed
    await _rule(db_session, "extension", user_id=user.id)
    decision = await decide(db_session, user, "extension")
    assert (decision.allowed, decision.reason) == (False, REASON_USER_DENY)
