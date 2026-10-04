"""Decide whether one account may use the web Chat or Projects.

The rules (:class:`app.models.feature_access.FeatureAccessRule`) and their
order, as the administrator sees them on the Feature Access page:

1. An administrator - anyone with an admin-panel role - always may.
2. A rule on the person decides, ``allow`` or ``deny``.
3. Otherwise a ``deny`` on any of their groups or on their department does.
4. Otherwise the section is open.

A section with no rules at all costs one small query and no role lookup,
which is the case for nearly every request on nearly every deployment.

This governs the web app only. The browser extension has its own access
(Chat Tools) and a personal API key goes through the gateway; neither asks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feature_access import FEATURE_CHAT, FEATURE_PROJECTS, FEATURES, FeatureAccessRule
from app.models.user import User, UserGroup, user_group_members
from app.services.rbac import user_is_admin_panel
from app.services.user_role_service import get_user_role_slugs

#: What a refusal answers with; the web app matches on ``code`` to show its "not enabled" page.
FEATURE_FORBIDDEN_CODE = "feature_not_enabled"

FEATURE_TITLES: dict[str, str] = {FEATURE_CHAT: "Chat", FEATURE_PROJECTS: "Projects"}

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


async def _rules(db: AsyncSession, features: Iterable[str]) -> list[FeatureAccessRule]:
    wanted = list(features)
    return list(
        (await db.execute(select(FeatureAccessRule).where(FeatureAccessRule.feature.in_(wanted)))).scalars().all()
    )


async def _group_ids(db: AsyncSession, user_id: int) -> set[int]:
    rows = await db.execute(select(user_group_members.c.group_id).where(user_group_members.c.user_id == user_id))
    return {int(value) for value in rows.scalars().all()}


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
    rules = await _rules(db, wanted)
    if not rules:
        return {feature: FeatureDecision(feature, True, REASON_DEFAULT) for feature in wanted}

    user_id = int(user.id)
    if user_is_admin_panel(await get_user_role_slugs(db, user_id)):
        return {feature: FeatureDecision(feature, True, REASON_ADMIN) for feature in wanted}

    group_ids: set[int] | None = None
    department = normalize_department(str(user.department) if user.department is not None else None)
    out: dict[str, FeatureDecision] = {}
    for feature in wanted:
        mine = [rule for rule in rules if rule.feature == feature]
        own = next((rule for rule in mine if rule.user_id is not None and int(rule.user_id) == user_id), None)
        if own is not None:
            allowed = str(own.effect) == "allow"
            out[feature] = FeatureDecision(
                feature, allowed, REASON_USER_ALLOW if allowed else REASON_USER_DENY, int(own.id)
            )
            continue
        decision: FeatureDecision | None = None
        group_rules = [rule for rule in mine if rule.group_id is not None and str(rule.effect) == "deny"]
        if group_rules:
            if group_ids is None:
                group_ids = await _group_ids(db, user_id)
            hit = next((rule for rule in group_rules if int(rule.group_id) in group_ids), None)
            if hit is not None:
                via = await _group_name(db, int(hit.group_id))
                decision = FeatureDecision(feature, False, REASON_GROUP_DENY, int(hit.id), via)
        if decision is None and department:
            hit = next(
                (
                    rule
                    for rule in mine
                    if rule.department is not None
                    and str(rule.effect) == "deny"
                    and normalize_department(str(rule.department)) == department
                ),
                None,
            )
            if hit is not None:
                decision = FeatureDecision(feature, False, REASON_DEPARTMENT_DENY, int(hit.id), str(hit.department))
        out[feature] = decision or FeatureDecision(feature, True, REASON_DEFAULT)
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
