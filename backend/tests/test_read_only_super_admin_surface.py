"""Every route that changes something must reject Read Only Super Admin.

Testing the role against a sample of endpoints proves nothing about the one
somebody adds next week. This walks the live route table instead and asserts a
structural property: no mutating route reaches the handler through a guard that
a platform-wide read-only role satisfies.

The guards that qualify are the menu/category ``write=True`` variants (which
call ``user_can_write_menu``), ``require_super_admin`` (which the read-only role
does not satisfy), and ``require_agent_permission`` (which resolves to an empty
permission set for it). A mutating admin route guarded only by a read variant
would be a hole, and this test is what says so.
"""

from __future__ import annotations

import inspect

from app.services.rbac import (
    AGENT_DOMAIN_PERMISSIONS,
    READ_ONLY_SUPER_ADMIN_SLUG,
    agent_permissions_for_slugs,
    user_can_write_menu,
)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: Pre-authentication or separately authenticated: no RBAC guard by design.
UNGUARDED_BY_DESIGN = {
    "/api/auth/login",
    "/api/auth/login/2fa",
    "/api/auth/saml/acs",
    "/api/auth/sso/exchange",
    "/api/auth/saml/exchange",
    "/v1/chat/completions",
    "/v1/embeddings",
    # The browser extension trades a one-time code or a refresh token here.
    "/api/extension/token",
}

#: POST only because the request carries a body; the handler reads and returns.
#: Both were read end to end: no session write, no commit, no audit event.
READ_SHAPED_POSTS = {
    "/api/admin/models/access-summary",
    "/api/admin/security/tls/certificates/{cert_id}/validate",
    "/api/admin/security/tls/verify",
}


def _routes():
    """Every route the app can serve, including the feature-flagged ones.

    ``app.main`` mounts the Agents & Knowledge routers only when the preview
    flag is on, and it does so at import time - setting the environment variable
    from inside a test is too late. Those routers are plain ``APIRouter``
    objects whose routes already carry their ``dependant``, so they are read
    directly rather than pretended about.
    """
    from app.main import app

    collected = []
    for entry in app.routes:
        inner = getattr(getattr(entry, "original_router", None), "routes", None)
        collected.extend(inner if inner else [entry])

    mounted = {id(r) for r in collected}
    from app.api import (
        admin_agent_evaluations,
        admin_agent_governance,
        admin_agents,
        admin_knowledge,
        agents,
    )

    for module in (
        admin_agent_evaluations,
        admin_agent_governance,
        admin_agents,
        admin_knowledge,
        agents,
    ):
        collected.extend(r for r in module.router.routes if id(r) not in mounted)
    return collected


def _guard_names(route) -> list[str]:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return []
    names = []
    for dependency in dependant.dependencies:
        call = dependency.call
        name = getattr(call, "__name__", repr(call))
        if name == "_check":
            # The menu/category/agent guards are closures built by a factory.
            nonlocals = inspect.getclosurevars(call).nonlocals
            if "menu" in nonlocals:
                name = f"menu:{nonlocals['menu']}:{'write' if nonlocals.get('write') else 'read'}"
            elif "menus" in nonlocals:
                name = f"category:{'write' if nonlocals.get('write') else 'read'}"
            elif "permission" in nonlocals:
                name = f"agent_permission:{nonlocals['permission']}"
        names.append(name)
    return names


def _blocks_global_read_only(guards: list[str]) -> bool:
    return any(g.endswith(":write") or g == "require_super_admin" or g.startswith("agent_permission:") for g in guards)


def _is_user_scoped(guards: list[str]) -> bool:
    return any(g in {"require_active_user", "get_current_user"} for g in guards)


def test_no_mutating_admin_route_admits_a_platform_wide_read_only_role():
    holes = []
    for route in _routes():
        methods = (getattr(route, "methods", None) or set()) & MUTATING
        if not methods:
            continue
        path = getattr(route, "path", "")
        if path in UNGUARDED_BY_DESIGN or path in READ_SHAPED_POSTS:
            continue
        guards = _guard_names(route)
        if _blocks_global_read_only(guards) or _is_user_scoped(guards):
            continue
        holes.append(f"{'/'.join(sorted(methods))} {path} guards={guards}")

    assert not holes, "mutating routes a read-only admin could reach:\n  " + "\n  ".join(holes)


def test_the_sweep_actually_covers_the_feature_flagged_routers():
    """Guards the guard: if the agents routers stopped being collected, the test
    above would pass by looking at nothing."""
    paths = {getattr(r, "path", "") for r in _routes()}
    assert any(p.startswith("/api/admin/agents") for p in paths)
    assert any(p.startswith("/api/admin/knowledge") for p in paths)


def test_the_role_can_write_no_admin_menu_at_all():
    """The guard above is only as good as what user_can_write_menu answers."""
    from app.services.rbac import MENU_LABELS, USER_APP_MENUS

    slugs = [READ_ONLY_SUPER_ADMIN_SLUG]
    for menu in MENU_LABELS:
        if menu in USER_APP_MENUS:
            continue
        assert not user_can_write_menu(slugs, menu), menu


def test_the_role_satisfies_no_writing_agent_permission():
    """require_agent_permission is the other way into a mutating handler.

    It holds the read permissions - without them the Agents menu appeared in the
    navigation and every endpoint behind it answered 403 - and no others. The
    combination case lives in test_role_combination_write_gate.py, which is
    where this test's single-slug view missed an escalation.
    """

    from app.services.rbac import AGENT_READ_PERMISSIONS

    slugs = [READ_ONLY_SUPER_ADMIN_SLUG]
    assert AGENT_DOMAIN_PERMISSIONS, "sanity: the permission set is not empty"
    assert agent_permissions_for_slugs(slugs) == AGENT_READ_PERMISSIONS
    assert agent_permissions_for_slugs(slugs) & (AGENT_DOMAIN_PERMISSIONS - AGENT_READ_PERMISSIONS) == frozenset()
