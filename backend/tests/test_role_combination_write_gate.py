"""Two write gates exist, and they have to agree for every combination of roles.

Almost every admin route is guarded by ``user_can_write_menu``, which takes ALL
semantics: every role that covers the menu must allow writing, so adding a
platform-wide read-only role caps whatever it is combined with.

The 45 mutating routes under Agents & Knowledge use ``require_agent_permission``
instead, which takes the UNION of every role's permissions and never consults
``user_can_write_menu``. So a read-only platform role plus any agents role
answered "no" to the menu gate and "yes" to the permission gate - the account
could permanently purge a Knowledge Base while the product reported it as
read-only.

The existing surface test evaluated one slug at a time, which is exactly why
this was invisible: the role is only dangerous in combination.
"""

from __future__ import annotations

import itertools

from app.services.rbac import (
    AGENT_DOMAIN_PERMISSIONS,
    AGENT_READ_PERMISSIONS,
    GLOBAL_READ_ONLY_SLUGS,
    READ_ONLY_SUPER_ADMIN_SLUG,
    REMOVED_ASSIGNABLE_ROLE_SLUGS,
    ROLE_BY_SLUG,
    SUPER_ADMIN_SLUG,
    agent_permissions_for_slugs,
    user_can_write_menu,
)

#: Everything in the domain that is not a read.
AGENT_WRITE_PERMISSIONS = AGENT_DOMAIN_PERMISSIONS - AGENT_READ_PERMISSIONS


def test_the_read_permission_split_is_exhaustive_and_sane():
    assert AGENT_READ_PERMISSIONS <= AGENT_DOMAIN_PERMISSIONS
    assert AGENT_WRITE_PERMISSIONS, "sanity: there are write permissions"
    assert "knowledge.purge" in AGENT_WRITE_PERMISSIONS
    assert "agent.read" in AGENT_READ_PERMISSIONS


def test_no_pair_of_roles_can_write_agents_while_the_menu_gate_says_no():
    """The invariant the two gates have to share."""

    slugs = sorted(set(ROLE_BY_SLUG) - REMOVED_ASSIGNABLE_ROLE_SLUGS)
    holes: list[str] = []
    for combination in itertools.combinations(slugs, 2):
        held = list(combination)
        if user_can_write_menu(held, "agents"):
            continue
        granted = agent_permissions_for_slugs(held) & AGENT_WRITE_PERMISSIONS
        if granted:
            holes.append(f"{held} -> {sorted(granted)}")

    assert not holes, (
        "role combinations that cannot write the Agents menu but hold write permissions:\n  " + "\n  ".join(holes)
    )


def test_the_specific_escalation_that_shipped():
    held = [READ_ONLY_SUPER_ADMIN_SLUG, "agents_administrator"]
    assert not user_can_write_menu(held, "agents")
    assert "knowledge.purge" not in agent_permissions_for_slugs(held)


def test_super_admin_paired_with_the_read_only_role_is_read_only():
    """Documented as 'assigning both makes the account read-only'."""

    held = [SUPER_ADMIN_SLUG, READ_ONLY_SUPER_ADMIN_SLUG]
    assert not user_can_write_menu(held, "agents")
    assert agent_permissions_for_slugs(held) & AGENT_WRITE_PERMISSIONS == frozenset()


def test_a_platform_wide_read_only_role_can_actually_see_agents():
    """The mirror of the escalation: the role got the menu and was 403'd by every route."""

    for slug in sorted(GLOBAL_READ_ONLY_SLUGS):
        granted = agent_permissions_for_slugs([slug])
        assert granted, f"{slug} sees the Agents menu but holds no permission at all"
        assert granted == AGENT_READ_PERMISSIONS, slug


def test_a_real_agents_role_on_its_own_still_writes():
    """The cap must not be a blanket removal of the feature."""

    granted = agent_permissions_for_slugs(["agents_administrator"])
    assert "knowledge.purge" in granted
    assert user_can_write_menu(["agents_administrator"], "agents")
