"""Evaluate and record who may use each chat tool.

Thin on purpose. The decision itself is
:func:`app.services.resource_access_service.evaluate_access` - the same "deny
wins, private needs an explicit allow, no implicit Super Admin bypass" rule
that governs agents, knowledge bases and catalog models. What this module adds
is where the policy for a *tool* is kept, and the fact that a tool with no
policy row falls back to the default in its registry entry.

Nothing here enumerates tools by name. Adding one to the registry is enough.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_tool import ChatToolAccessAssignment, ChatToolPolicy
from app.services.chat_tool_registry import (
    CHAT_TOOLS,
    ChatToolSpec,
    spec_or_none,
)
from app.services.resource_access_service import (
    VALID_ACCESS_TYPES,
    AccessGrant,
    ResourceAccessSubject,
    validated_grants,
    evaluate_access,
)

#: What a refused tool answers with. The client matches on ``code`` to point
#: at the toggle it has to turn off, so it is part of the contract.
TOOL_FORBIDDEN_CODE = "tool_not_permitted"


def _forbidden(spec: ChatToolSpec) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": TOOL_FORBIDDEN_CODE,
            "tool": spec.key,
            "message": f"{spec.title} is not available to your account.",
        },
    )


async def _policies(db: AsyncSession, keys: Sequence[str]) -> dict[str, ChatToolPolicy]:
    if not keys:
        return {}
    rows = (await db.execute(select(ChatToolPolicy).where(ChatToolPolicy.tool_key.in_(keys)))).scalars().all()
    return {str(row.tool_key): row for row in rows}


async def _assignments(db: AsyncSession, keys: Sequence[str]) -> dict[str, list[ChatToolAccessAssignment]]:
    if not keys:
        return {}
    rows = (
        (await db.execute(select(ChatToolAccessAssignment).where(ChatToolAccessAssignment.tool_key.in_(keys))))
        .scalars()
        .all()
    )
    grouped: dict[str, list[ChatToolAccessAssignment]] = {key: [] for key in keys}
    for row in rows:
        grouped.setdefault(str(row.tool_key), []).append(row)
    return grouped


def _access_type(spec: ChatToolSpec, policy: ChatToolPolicy | None) -> str:
    if policy is None:
        return spec.default_access
    return str(policy.access_type or spec.default_access)


async def permitted_tool_keys(
    db: AsyncSession,
    subject: ResourceAccessSubject,
    *,
    keys: Iterable[str] | None = None,
) -> frozenset[str]:
    """Which of ``keys`` (default: every registered tool) this subject may use."""

    specs = [spec for spec in CHAT_TOOLS if keys is None or spec.key in set(keys)]
    if not specs:
        return frozenset()
    wanted = [spec.key for spec in specs]
    policies = await _policies(db, wanted)
    assignments = await _assignments(db, wanted)
    return frozenset(
        spec.key
        for spec in specs
        if evaluate_access(
            access_type=_access_type(spec, policies.get(spec.key)),
            assignments=assignments.get(spec.key, []),
            subject=subject,
        )
    )


async def assert_tools_permitted(
    db: AsyncSession,
    subject: ResourceAccessSubject,
    requested: Iterable[str],
) -> None:
    """Raise 403 for the first requested tool this subject may not use.

    A turn that asks for nothing costs nothing: with no requested tools this
    returns without touching the database, which is the common case.
    """

    wanted = sorted({key for key in requested if spec_or_none(key) is not None})
    if not wanted:
        return
    allowed = await permitted_tool_keys(db, subject, keys=wanted)
    for key in wanted:
        if key not in allowed:
            spec = spec_or_none(key)
            assert spec is not None  # filtered above
            raise _forbidden(spec)


async def get_chat_tool_access(db: AsyncSession, key: str) -> dict[str, Any]:
    """The saved policy of one tool, in the shape the ACL editor reads."""

    spec = spec_or_none(key)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown chat tool '{key}'.")
    policy = (await _policies(db, [spec.key])).get(spec.key)
    rows = (await _assignments(db, [spec.key])).get(spec.key, [])
    grants: list[dict[str, Any]] = []
    for row in rows:
        if row.user_id is not None:
            grants.append({"target_type": "user", "target": int(row.user_id), "effect": row.effect})
        elif row.group_id is not None:
            grants.append({"target_type": "group", "target": int(row.group_id), "effect": row.effect})
        elif row.department:
            grants.append({"target_type": "department", "target": row.department, "effect": row.effect})
        elif row.role_slug:
            grants.append({"target_type": "role", "target": row.role_slug, "effect": row.effect})
    return {
        "tool_key": spec.key,
        "access_type": _access_type(spec, policy),
        "acl_version": int(policy.acl_version or 0) if policy is not None else 0,
        "grants": grants,
        "updated_at": policy.updated_at.isoformat() if policy is not None and policy.updated_at else None,
        "updated_by_user_id": policy.updated_by_user_id if policy is not None else None,
    }


async def set_chat_tool_access(
    db: AsyncSession,
    key: str,
    *,
    access_type: str,
    grants: Sequence[AccessGrant],
    assigned_by_user_id: int | None = None,
) -> dict[str, Any]:
    """Replace one tool's policy and grants. Returns the saved state."""

    spec = spec_or_none(key)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown chat tool '{key}'.")
    access = (access_type or "").strip().lower()
    if access not in VALID_ACCESS_TYPES:
        raise ValueError("access_type must be 'public' or 'private'")
    rows = await validated_grants(db, grants)

    policy = await db.get(ChatToolPolicy, spec.key)
    if policy is None:
        policy = ChatToolPolicy(tool_key=spec.key, access_type=access, acl_version=0)
        db.add(policy)
    policy.access_type = access
    policy.acl_version = int(policy.acl_version or 0) + 1
    policy.updated_at = datetime.utcnow()
    policy.updated_by_user_id = assigned_by_user_id

    await db.execute(delete(ChatToolAccessAssignment).where(ChatToolAccessAssignment.tool_key == spec.key))
    for row in rows:
        db.add(
            ChatToolAccessAssignment(
                tool_key=spec.key,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=datetime.utcnow(),
                **row,
            )
        )
    await db.flush()
    return await get_chat_tool_access(db, spec.key)


async def chat_tool_overview(db: AsyncSession) -> list[dict[str, Any]]:
    """Every registered tool with its saved policy, for the admin page.

    One row per registry entry, whether or not anybody has saved a policy for
    it - so a tool registered this morning is on the page this afternoon.
    """

    keys = [spec.key for spec in CHAT_TOOLS]
    policies = await _policies(db, keys)
    assignments = await _assignments(db, keys)
    out: list[dict[str, Any]] = []
    for spec in CHAT_TOOLS:
        policy = policies.get(spec.key)
        rows = assignments.get(spec.key, [])
        out.append(
            {
                "key": spec.key,
                "title": spec.title,
                "description": spec.description,
                "icon": spec.icon,
                "access_type": _access_type(spec, policy),
                "acl_version": int(policy.acl_version or 0) if policy is not None else 0,
                "allow_count": sum(1 for row in rows if (row.effect or "allow") == "allow"),
                "deny_count": sum(1 for row in rows if (row.effect or "allow") == "deny"),
                "updated_at": policy.updated_at.isoformat() if policy is not None and policy.updated_at else None,
                "updated_by_user_id": policy.updated_by_user_id if policy is not None else None,
            }
        )
    return out
