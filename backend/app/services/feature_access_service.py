"""Decide whether one account may use the web Chat or Projects.

The rules (:class:`app.models.feature_access.FeatureAccessRule`) and their
order, as the administrator sees them on the Feature Access page:

1. An administrator - anyone with an admin-panel role - always may.
2. A rule on the person decides, ``allow`` or ``deny``.
3. Otherwise a ``deny`` on any of their groups or on their department does.
4. Otherwise the section is open.

A person no rule names - on them, their groups or their department - costs
one small query and no role lookup, which is the case for nearly every
request on nearly every deployment.

Chat and Projects govern the web app only: the browser extension has its
own access (Chat Tools). API keys governs the person's own keys - making
one, and every use of one at the gateway. Keys an administrator issues on
the API Keys page are not personal keys and are not governed here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feature_access import FEATURE_API_KEYS, FEATURE_CHAT, FEATURE_PROJECTS, FEATURES, FeatureAccessRule
from app.models.user import User, UserGroup, user_group_members
from app.services.rbac import user_is_admin_panel
from app.services.user_role_service import get_user_role_slugs

#: What a refusal answers with; the web app matches on ``code`` to show its "not enabled" page.
FEATURE_FORBIDDEN_CODE = "feature_not_enabled"

FEATURE_TITLES: dict[str, str] = {FEATURE_CHAT: "Chat", FEATURE_PROJECTS: "Projects", FEATURE_API_KEYS: "API keys"}

#: Why a decision came out the way it did; the admin "check a user" tool shows it.
REASON_DEFAULT = "default"
REASON_ADMIN = "admin"
REASON_USER_ALLOW = "user_allow"
REASON_USER_DENY = "user_deny"
REASON_GROUP_DENY = "group_deny"
REASON_DEPARTMENT_DENY = "department_deny"


@dataclass(frozen=True)
class FeatureDecision:
    feature: str
    allowed: bool
    reason: str
    #: The rule that decided, when one did.
    rule_id: int | None = None
    #: The group's name or the department, for a group or department rule.
    via: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "allowed": self.allowed,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "via": self.via,
        }


def normalize_department(value: str | None) -> str | None:
    """Department names match whatever their case and spacing."""
    if value is None:
        return None
    normalized = " ".join(str(value).split()).casefold()
    return normalized or None


def validate_feature(feature: str) -> str:
    key = (feature or "").strip().lower()
    if key not in FEATURES:
        raise HTTPException(status_code=404, detail=f"Unknown feature '{feature}'.")
    return key


async def _rules_for(db: AsyncSession, features: Iterable[str], user: User) -> list[FeatureAccessRule]:
    """The rules that can apply to this person: on them, on one of their groups, or on their department.

    Filtered in SQL for the person and their groups; department rules are few
    and are matched here, whatever their case and spacing.
    """
    user_id = int(user.id)
    their_groups = select(user_group_members.c.group_id).where(user_group_members.c.user_id == user_id)
    rows = (
        (
            await db.execute(
                select(FeatureAccessRule).where(
                    FeatureAccessRule.feature.in_(list(features)),
                    or_(
                        FeatureAccessRule.user_id == user_id,
                        FeatureAccessRule.group_id.in_(their_groups),
                        FeatureAccessRule.department.is_not(None),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    department = normalize_department(str(user.department) if user.department is not None else None)
    return [
        rule
        for rule in rows
        if rule.department is None or (department and normalize_department(str(rule.department)) == department)
    ]


async def _group_name(db: AsyncSession, group_id: int) -> str:
    group = await db.get(UserGroup, group_id)
    return str(group.name) if group is not None else f"Group #{group_id}"


async def decide_all(
    db: AsyncSession,
    user: User,
    features: Iterable[str] = FEATURES,
) -> dict[str, FeatureDecision]:
    """The decision for each of ``features``, loading the person's roles and groups at most once."""

    wanted = [validate_feature(feature) for feature in features]
    rules = await _rules_for(db, wanted, user)
    if not rules:
        # No rule names this person, their groups or their department: open, and no role lookup.
        return {feature: FeatureDecision(feature, True, REASON_DEFAULT) for feature in wanted}

    user_id = int(user.id)
    if user_is_admin_panel(await get_user_role_slugs(db, user_id)):
        return {feature: FeatureDecision(feature, True, REASON_ADMIN) for feature in wanted}

    out: dict[str, FeatureDecision] = {}
    for feature in wanted:
        mine = [rule for rule in rules if rule.feature == feature]
        own = next((rule for rule in mine if rule.user_id is not None), None)
        if own is not None:
            allowed = str(own.effect) == "allow"
            out[feature] = FeatureDecision(
                feature, allowed, REASON_USER_ALLOW if allowed else REASON_USER_DENY, int(own.id)
            )
            continue
        group_hit = next((rule for rule in mine if rule.group_id is not None and str(rule.effect) == "deny"), None)
        if group_hit is not None:
            via = await _group_name(db, int(group_hit.group_id))
            out[feature] = FeatureDecision(feature, False, REASON_GROUP_DENY, int(group_hit.id), via)
            continue
        dept_hit = next((rule for rule in mine if rule.department is not None and str(rule.effect) == "deny"), None)
        if dept_hit is not None:
            out[feature] = FeatureDecision(
                feature, False, REASON_DEPARTMENT_DENY, int(dept_hit.id), str(dept_hit.department)
            )
            continue
        out[feature] = FeatureDecision(feature, True, REASON_DEFAULT)
    return out


async def decide(db: AsyncSession, user: User, feature: str) -> FeatureDecision:
    return (await decide_all(db, user, [feature]))[validate_feature(feature)]


async def feature_enabled(db: AsyncSession, user: User, feature: str) -> bool:
    return (await decide(db, user, feature)).allowed


async def feature_enabled_for_user_id(db: AsyncSession, user_id: int, feature: str) -> bool:
    """For background work, which has the owner's id: a missing account may use nothing."""
    user = await db.get(User, int(user_id))
    if user is None:
        return False
    return await feature_enabled(db, user, feature)


def feature_forbidden(feature: str) -> HTTPException:
    title = FEATURE_TITLES.get(feature, feature)
    return HTTPException(
        status_code=403,
        detail={
            "code": FEATURE_FORBIDDEN_CODE,
            "feature": feature,
            "message": f"{title} is not enabled for your account. Ask your administrator if you need it.",
        },
    )


async def require_feature(db: AsyncSession, user: User, feature: str) -> None:
    """Raise 403 when this account may not use ``feature``."""
    if not await feature_enabled(db, user, feature):
        raise feature_forbidden(feature)


__all__ = [
    "FEATURE_API_KEYS",
    "FEATURE_CHAT",
    "FEATURE_FORBIDDEN_CODE",
    "FEATURE_PROJECTS",
    "FeatureDecision",
    "decide",
    "decide_all",
    "feature_enabled",
    "feature_enabled_for_user_id",
    "feature_forbidden",
    "normalize_department",
    "require_feature",
]
