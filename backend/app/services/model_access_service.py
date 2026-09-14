"""Catalog model Public/Private access control (users + groups)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey
from app.models.model_catalog import AIModel, ModelAccessAssignment
from app.models.user import User, UserGroup, user_group_members
from app.services.rbac import user_has_super_admin_access
from app.services.user_role_service import get_user_role_slugs

ACCESS_PUBLIC = "public"
ACCESS_PRIVATE = "private"
VALID_ACCESS_TYPES = frozenset({ACCESS_PUBLIC, ACCESS_PRIVATE})


@dataclass(frozen=True)
class ModelAccessSubject:
    """Resolved subject for ACL evaluation."""

    user_id: int | None = None
    unrestricted: bool = False  # super admin
    public_only: bool = False  # master key / Alpharouter key without owner


async def resolve_access_subject(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    source: str | None = None,
) -> ModelAccessSubject:
    """Map chat session / gateway auth context to an ACL subject."""
    if source == "master":
        return ModelAccessSubject(public_only=True)

    if alpha_router_api_key_id is not None:
        key = await db.get(AlphaRouterApiKey, alpha_router_api_key_id)
        owner_id = int(key.owner_user_id) if key and key.owner_user_id is not None else None
        if owner_id is None:
            return ModelAccessSubject(public_only=True)
        slugs = await get_user_role_slugs(db, owner_id)
        if user_has_super_admin_access(slugs):
            return ModelAccessSubject(user_id=owner_id, unrestricted=True)
        return ModelAccessSubject(user_id=owner_id)

    if user_id is not None:
        slugs = await get_user_role_slugs(db, user_id)
        if user_has_super_admin_access(slugs):
            return ModelAccessSubject(user_id=user_id, unrestricted=True)
        return ModelAccessSubject(user_id=user_id)

    return ModelAccessSubject(public_only=True)


async def _user_group_ids(db: AsyncSession, user_id: int) -> set[int]:
    rows = (
        (await db.execute(select(user_group_members.c.group_id).where(user_group_members.c.user_id == user_id)))
        .scalars()
        .all()
    )
    return {int(g) for g in rows}


async def user_can_access_model(
    db: AsyncSession,
    model: AIModel,
    subject: ModelAccessSubject,
) -> bool:
    if subject.unrestricted:
        return True
    access = (model.access_type or ACCESS_PUBLIC).strip().lower()
    if access != ACCESS_PRIVATE:
        return True
    if subject.public_only or subject.user_id is None:
        return False
    assigned = (
        await db.execute(
            select(ModelAccessAssignment.id)
            .where(
                ModelAccessAssignment.model_id == model.id,
                or_(
                    ModelAccessAssignment.user_id == subject.user_id,
                    ModelAccessAssignment.group_id.in_(
                        select(user_group_members.c.group_id).where(user_group_members.c.user_id == subject.user_id)
                    ),
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return assigned is not None


async def filter_models_for_subject(
    db: AsyncSession,
    models: list[AIModel],
    subject: ModelAccessSubject,
) -> list[AIModel]:
    if subject.unrestricted:
        return models
    if not models:
        return []
    if subject.public_only or subject.user_id is None:
        return [m for m in models if (m.access_type or ACCESS_PUBLIC).strip().lower() != ACCESS_PRIVATE]

    private_ids = [m.id for m in models if (m.access_type or ACCESS_PUBLIC).strip().lower() == ACCESS_PRIVATE]
    if not private_ids:
        return models

    group_ids = await _user_group_ids(db, subject.user_id)
    allowed_private: set[int] = set()
    rows = (
        await db.execute(
            select(
                ModelAccessAssignment.model_id,
                ModelAccessAssignment.user_id,
                ModelAccessAssignment.group_id,
            ).where(ModelAccessAssignment.model_id.in_(private_ids))
        )
    ).all()
    for model_id, uid, gid in rows:
        if uid is not None and int(uid) == subject.user_id or gid is not None and int(gid) in group_ids:
            allowed_private.add(int(model_id))

    out: list[AIModel] = []
    for m in models:
        if (m.access_type or ACCESS_PUBLIC).strip().lower() != ACCESS_PRIVATE or m.id in allowed_private:
            out.append(m)
    return out


async def set_model_access(
    db: AsyncSession,
    model: AIModel,
    *,
    access_type: str,
    user_ids: list[int] | None = None,
    group_ids: list[int] | None = None,
) -> None:
    access = (access_type or "").strip().lower()
    if access not in VALID_ACCESS_TYPES:
        raise ValueError("access_type must be 'public' or 'private'")

    model.access_type = access
    await db.execute(delete(ModelAccessAssignment).where(ModelAccessAssignment.model_id == model.id))

    if access == ACCESS_PUBLIC:
        return

    clean_users = list(dict.fromkeys(int(x) for x in (user_ids or []) if x is not None))
    clean_groups = list(dict.fromkeys(int(x) for x in (group_ids or []) if x is not None))

    if clean_users:
        existing_users = set(
            (await db.execute(select(User.id).where(User.id.in_(clean_users), User.deleted_at.is_(None))))
            .scalars()
            .all()
        )
        for uid in clean_users:
            if uid not in existing_users:
                continue
            db.add(
                ModelAccessAssignment(
                    model_id=model.id,
                    user_id=uid,
                    group_id=None,
                    assigned_at=datetime.utcnow(),
                )
            )

    if clean_groups:
        existing_groups = set(
            (await db.execute(select(UserGroup.id).where(UserGroup.id.in_(clean_groups)))).scalars().all()
        )
        for gid in clean_groups:
            if gid not in existing_groups:
                continue
            db.add(
                ModelAccessAssignment(
                    model_id=model.id,
                    user_id=None,
                    group_id=gid,
                    assigned_at=datetime.utcnow(),
                )
            )


async def bulk_set_access_type(
    db: AsyncSession,
    model_ids: list[int],
    access_type: str,
) -> int:
    access = (access_type or "").strip().lower()
    if access not in VALID_ACCESS_TYPES:
        raise ValueError("access_type must be 'public' or 'private'")
    if not model_ids:
        return 0
    ids = list(dict.fromkeys(int(x) for x in model_ids))
    result = await db.execute(update(AIModel).where(AIModel.id.in_(ids)).values(access_type=access))
    if access == ACCESS_PUBLIC:
        await db.execute(delete(ModelAccessAssignment).where(ModelAccessAssignment.model_id.in_(ids)))
    return result.rowcount or 0


async def list_assignment_counts(db: AsyncSession, model_ids: list[int]) -> dict[int, dict[str, int]]:
    if not model_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ModelAccessAssignment.model_id,
                func.count(ModelAccessAssignment.user_id),
                func.count(ModelAccessAssignment.group_id),
            )
            .where(ModelAccessAssignment.model_id.in_(model_ids))
            .group_by(ModelAccessAssignment.model_id)
        )
    ).all()
    out = {mid: {"users": 0, "groups": 0} for mid in model_ids}
    for mid, user_count, group_count in rows:
        out[int(mid)] = {"users": int(user_count or 0), "groups": int(group_count or 0)}
    return out


async def get_model_access_detail(db: AsyncSession, model_id: int) -> dict | None:
    model = await db.get(AIModel, model_id)
    if not model:
        return None
    assignments = (
        (await db.execute(select(ModelAccessAssignment).where(ModelAccessAssignment.model_id == model_id)))
        .scalars()
        .all()
    )
    user_ids = [a.user_id for a in assignments if a.user_id is not None]
    group_ids = [a.group_id for a in assignments if a.group_id is not None]

    users: list[dict] = []
    if user_ids:
        urows = (await db.execute(select(User).where(User.id.in_(user_ids), User.deleted_at.is_(None)))).scalars().all()
        users = [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email or "",
                "display_name": u.display_name,
            }
            for u in urows
        ]

    groups: list[dict] = []
    if group_ids:
        grows = (await db.execute(select(UserGroup).where(UserGroup.id.in_(group_ids)))).scalars().all()
        groups = [{"id": g.id, "name": g.name, "source": g.source or "local"} for g in grows]

    return {
        "model_id": model.id,
        "access_type": (model.access_type or ACCESS_PUBLIC).strip().lower(),
        "users": users,
        "groups": groups,
    }
