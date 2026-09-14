"""Project lifecycle, membership, and invitation management.

All mutations re-read membership from the database at the time of the
operation (never trusting client-supplied roles) and enforce Primary Owner
protection via ``ensure_not_last_owner``.  Every state change appends an
immutable audit event.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession, ai_channel_filter
from app.models.project import (
    PROJECT_RESOURCE_STATUS_REVOKED,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_STATUS_ACTIVE,
    PROJECT_STATUS_ARCHIVED,
    PROJECT_STATUS_DELETION_PENDING,
    PROJECT_VISIBILITY_PRIVATE,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectInvitation,
    ProjectMediaAsset,
    ProjectMember,
    ProjectResource,
    ProjectUserPref,
)
from app.models.user import User
from app.services.project_access_service import (
    ProjectAccessError,
    append_project_audit,
    bump_acl_version,
    can_view_project_activity,
    ensure_not_last_owner,
    ensure_primary_owner_protected,
    is_primary_owner_role,
    is_project_owner_role,
    require_capability,
    resolve_project_access,
    validate_invitation_role,
    validate_role,
)

PROJECT_NAME_MAX = 255
PROJECT_DESCRIPTION_MAX = 4000
INVITATION_DEFAULT_TTL_DAYS = 7
INVITATION_MAX_TTL_DAYS = 30
PROJECT_LIST_DEFAULT_LIMIT = 50
PROJECT_LIST_MAX_LIMIT = 100
PROJECT_DELETION_RETENTION_DAYS = 30


class ProjectValidationError(ValueError):
    """Raised when user-supplied project input is invalid."""


def _new_id() -> str:
    return str(uuid.uuid4())


def _normalize_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise ProjectValidationError("Project name is required")
    if len(normalized) > PROJECT_NAME_MAX:
        raise ProjectValidationError(f"Project name must be at most {PROJECT_NAME_MAX} characters")
    return normalized


def _normalize_description(description: str | None) -> str | None:
    if not description:
        return None
    text = description.strip()
    if len(text) > PROJECT_DESCRIPTION_MAX:
        raise ProjectValidationError(f"Project description must be at most {PROJECT_DESCRIPTION_MAX} characters")
    return text or None


def _serialize_project(project: Project, *, role: str | None = None, is_member: bool = False) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "visibility": project.visibility,
        "createdByUserId": project.created_by_user_id,
        "revision": project.revision,
        "aclVersion": project.acl_version,
        "createdAt": project.created_at.isoformat() if project.created_at else None,
        "updatedAt": project.updated_at.isoformat() if project.updated_at else None,
        "archivedAt": project.archived_at.isoformat() if project.archived_at else None,
        "myRole": role,
        "isMember": is_member,
    }


def _serialize_member(
    member: ProjectMember, *, username: str | None = None, display_name: str | None = None
) -> dict[str, Any]:
    return {
        "projectId": member.project_id,
        "userId": member.user_id,
        "role": member.role,
        "username": username,
        "displayName": display_name,
        "invitedByUserId": member.invited_by_user_id,
        "createdAt": member.created_at.isoformat() if member.created_at else None,
        "updatedAt": member.updated_at.isoformat() if member.updated_at else None,
    }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------


async def create_project(
    db: AsyncSession,
    *,
    user: User,
    name: str,
    description: str | None = None,
    visibility: str = PROJECT_VISIBILITY_PRIVATE,
) -> dict[str, Any]:
    clean_name = _normalize_name(name)
    clean_desc = _normalize_description(description)
    if visibility not in (PROJECT_VISIBILITY_PRIVATE, PROJECT_VISIBILITY_PUBLIC):
        raise ProjectValidationError("Invalid visibility")

    project_id = _new_id()
    project = Project(
        id=project_id,
        name=clean_name,
        description=clean_desc,
        status=PROJECT_STATUS_ACTIVE,
        visibility=visibility,
        created_by_user_id=user.id,
        revision=1,
        acl_version=1,
    )
    db.add(project)
    await db.flush()

    owner_member = ProjectMember(
        project_id=project_id,
        user_id=user.id,
        role=PROJECT_ROLE_PRIMARY_OWNER,
        invited_by_user_id=user.id,
    )
    db.add(owner_member)
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.created",
        actor_user_id=user.id,
        payload={"name": clean_name, "visibility": visibility},
    )
    return _serialize_project(project, role=PROJECT_ROLE_PRIMARY_OWNER, is_member=True)


async def get_project(db: AsyncSession, *, project_id: str, user: User) -> dict[str, Any] | None:
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    project = await db.get(Project, project_id)
    if project is None:
        return None
    return _serialize_project(project, role=access.role, is_member=access.is_member)


async def list_my_projects(
    db: AsyncSession,
    *,
    user: User,
    limit: int = PROJECT_LIST_DEFAULT_LIMIT,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    limit = max(1, min(limit, PROJECT_LIST_MAX_LIMIT))
    offset = max(0, offset)
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProjectMember)
                .join(Project, Project.id == ProjectMember.project_id)
                .where(
                    ProjectMember.user_id == user.id,
                )
            )
        ).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == user.id,
            )
            .order_by(Project.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_serialize_project(p, role=role, is_member=True) for p, role in rows], total


async def list_public_projects(
    db: AsyncSession,
    *,
    user: User,
    limit: int = PROJECT_LIST_DEFAULT_LIMIT,
    offset: int = 0,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Public projects the caller is *not* already a member of (Explore view)."""
    limit = max(1, min(limit, PROJECT_LIST_MAX_LIMIT))
    offset = max(0, offset)

    member_ids_subq = (select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).subquery()

    base = select(Project).where(
        Project.visibility == PROJECT_VISIBILITY_PUBLIC,
        Project.status == PROJECT_STATUS_ACTIVE,
        Project.id.not_in(select(member_ids_subq.c.project_id)),
    )
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(Project.name.ilike(like), Project.description.ilike(like)))

    total = int((await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one() or 0)
    rows = (await db.execute(base.order_by(Project.updated_at.desc()).limit(limit).offset(offset))).scalars().all()
    return [_serialize_project(p, role=PROJECT_ROLE_VIEWER, is_member=False) for p in rows], total


RECENT_PROJECTS_DEFAULT_LIMIT = 8
RECENT_PROJECTS_MAX_LIMIT = 20


async def list_recent_projects(
    db: AsyncSession,
    *,
    user: User,
    limit: int = RECENT_PROJECTS_DEFAULT_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Projects this user opened most recently, still accessible."""
    limit = max(1, min(limit, RECENT_PROJECTS_MAX_LIMIT))
    rows = (
        await db.execute(
            select(ProjectUserPref, Project)
            .join(Project, Project.id == ProjectUserPref.project_id)
            .where(ProjectUserPref.user_id == user.id)
            .order_by(ProjectUserPref.last_opened_at.desc())
            .limit(limit * 3)
        )
    ).all()
    out: list[dict[str, Any]] = []
    for _pref, project in rows:
        access = await resolve_project_access(db, project_id=project.id, user=user)
        if access is None:
            continue
        if project.status != PROJECT_STATUS_ACTIVE:
            continue
        out.append(_serialize_project(project, role=access.role, is_member=access.is_member))
        if len(out) >= limit:
            break
    return out, len(out)


async def get_project_overview(db: AsyncSession, *, project_id: str, user: User) -> dict[str, Any] | None:
    """Workspace overview: counts for all members; spend only with Activity ACL."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    project = await db.get(Project, project_id)
    if project is None:
        return None

    member_count = int(
        (
            await db.execute(
                select(func.count()).select_from(ProjectMember).where(ProjectMember.project_id == project_id)
            )
        ).scalar_one()
        or 0
    )
    chat_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ChatSession)
                .where(
                    ChatSession.project_id == project_id,
                    ChatSession.archived_at.is_(None),
                    ai_channel_filter(),
                )
            )
        ).scalar_one()
        or 0
    )
    resource_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProjectResource)
                .where(
                    ProjectResource.project_id == project_id,
                    ProjectResource.status != PROJECT_RESOURCE_STATUS_REVOKED,
                )
            )
        ).scalar_one()
        or 0
    )
    media_count = int(
        (
            await db.execute(
                select(func.count()).select_from(ProjectMediaAsset).where(ProjectMediaAsset.project_id == project_id)
            )
        ).scalar_one()
        or 0
    )

    payload: dict[str, Any] = {
        "project": _serialize_project(project, role=access.role, is_member=access.is_member),
        "counts": {
            "members": member_count,
            "chats": chat_count,
            "resources": resource_count,
            "media": media_count,
        },
        "usage": None,
    }
    if await can_view_project_activity(db, project_id=project_id, user=user):
        from app.services.project_billing_service import report_project_usage_summary

        end = datetime.datetime.utcnow()
        start = end - datetime.timedelta(days=30)
        df = await report_project_usage_summary(db, project_id, start, end)
        row = df.iloc[0].to_dict() if df is not None and not df.empty else {}
        payload["usage"] = {
            "windowDays": 30,
            "totalCostUsd": round(float(row.get("total_cost_usd") or 0), 4),
            "mediaCostUsd": round(float(row.get("media_cost_usd") or 0), 4),
            "requests": int(row.get("requests") or 0),
            "totalTokens": int(row.get("total_tokens") or 0),
        }
    return payload


async def update_project(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    name: str | None = None,
    description: str | None = None,
    visibility: str | None = None,
    confirm_public_name: str | None = None,
) -> dict[str, Any]:
    access = await require_capability(db, project_id=project_id, user=user, capability="project.edit")
    project = await db.get(Project, project_id)
    if project is None:
        raise ProjectValidationError("Project not found")
    if (
        visibility == PROJECT_VISIBILITY_PUBLIC
        and project.visibility != PROJECT_VISIBILITY_PUBLIC
        and (confirm_public_name or "").strip() != (project.name or "").strip()
    ):
        # Going public exposes chats and knowledge to every active user. The
        # client must echo the project name back so a mis-click cannot do it.
        raise ProjectValidationError("To make this project public, repeat its exact name in confirm_public_name")

    changes: dict[str, Any] = {}
    if name is not None:
        project.name = _normalize_name(name)
        changes["name"] = project.name
    if description is not None:
        project.description = _normalize_description(description)
        changes["description"] = project.description
    if visibility is not None:
        if visibility not in (PROJECT_VISIBILITY_PRIVATE, PROJECT_VISIBILITY_PUBLIC):
            raise ProjectValidationError("Invalid visibility")
        if project.visibility != visibility:
            project.visibility = visibility
            changes["visibility"] = visibility
            await bump_acl_version(db, project)
            if visibility == PROJECT_VISIBILITY_PUBLIC:
                await append_project_audit(
                    db,
                    project_id=project_id,
                    event_type="project.visibility.public",
                    actor_user_id=user.id,
                    payload={"name": project.name, "confirmed": True},
                )

    project.revision = int(project.revision or 1) + 1
    project.updated_at = datetime.datetime.utcnow()
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.updated",
        actor_user_id=user.id,
        payload=changes,
    )
    return _serialize_project(project, role=access.role, is_member=access.is_member)


async def delete_project(db: AsyncSession, *, project_id: str, user: User) -> bool:
    """Soft-delete: marks the project deletion_pending."""
    await require_capability(db, project_id=project_id, user=user, capability="project.delete")
    project = await db.get(Project, project_id)
    if project is None:
        return False
    if project.status == PROJECT_STATUS_DELETION_PENDING:
        return True

    previous = project.status
    project.status = PROJECT_STATUS_DELETION_PENDING
    project.updated_at = datetime.datetime.utcnow()
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.deleted",
        actor_user_id=user.id,
        payload={"previous_status": previous},
    )
    return True


async def archive_project(db: AsyncSession, *, project_id: str, user: User) -> dict[str, Any] | None:
    """Hide a project from Explore while keeping membership and chats."""
    access = await require_capability(db, project_id=project_id, user=user, capability="project.delete")
    project = await db.get(Project, project_id)
    if project is None:
        return None
    if project.status == PROJECT_STATUS_DELETION_PENDING:
        raise ProjectValidationError("Cannot archive a project that is pending deletion")
    if project.status != PROJECT_STATUS_ARCHIVED:
        project.status = PROJECT_STATUS_ARCHIVED
        project.archived_at = datetime.datetime.utcnow()
        project.updated_at = datetime.datetime.utcnow()
        await db.flush()
        await append_project_audit(
            db,
            project_id=project_id,
            event_type="project.archived",
            actor_user_id=user.id,
        )
    return _serialize_project(project, role=access.role, is_member=access.is_member)


async def restore_project(db: AsyncSession, *, project_id: str, user: User) -> dict[str, Any] | None:
    """Restore an archived project to active."""
    access = await require_capability(db, project_id=project_id, user=user, capability="project.delete")
    project = await db.get(Project, project_id)
    if project is None:
        return None
    if project.status == PROJECT_STATUS_DELETION_PENDING:
        raise ProjectValidationError("Cannot restore a project that is pending deletion")
    if project.status != PROJECT_STATUS_ACTIVE:
        project.status = PROJECT_STATUS_ACTIVE
        project.archived_at = None
        project.updated_at = datetime.datetime.utcnow()
        await db.flush()
        await append_project_audit(
            db,
            project_id=project_id,
            event_type="project.restored",
            actor_user_id=user.id,
        )
    return _serialize_project(project, role=access.role, is_member=access.is_member)


async def _purge_project_rows(
    db: AsyncSession,
    project: Project,
    *,
    object_store: Any | None = None,
) -> None:
    from app.services.project_media_service import cleanup_project_media_storage
    from app.services.project_memory_service import purge_project_memory_index

    await cleanup_project_media_storage(db, project.id, object_store=object_store)
    await db.execute(delete(ProjectMediaAsset).where(ProjectMediaAsset.project_id == project.id))
    # Qdrant is a derived index outside the Postgres cascade, so drop the
    # project's vectors explicitly before the rows disappear.
    await purge_project_memory_index(project.id)
    await db.delete(project)
    await db.flush()


async def hard_delete_project(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    object_store: Any | None = None,
    require_pending: bool = False,
) -> bool:
    """Permanently delete a project after sweeping project-owned object storage.

    Blob cleanup must run while media rows still exist so storage paths are
    known. Rows are then deleted explicitly (SQLite tests may not enforce
    FK CASCADE) before the project row itself is removed.
    """
    await require_capability(db, project_id=project_id, user=user, capability="project.delete")
    project = await db.get(Project, project_id)
    if project is None:
        return False
    if require_pending and project.status != PROJECT_STATUS_DELETION_PENDING:
        raise ProjectValidationError("Only deletion-pending projects can be purged")

    await _purge_project_rows(db, project, object_store=object_store)
    return True


async def purge_expired_deleted_projects(
    db: AsyncSession,
    *,
    retention_days: int = PROJECT_DELETION_RETENTION_DAYS,
    object_store: Any | None = None,
) -> int:
    """Hard-delete projects that have been deletion-pending longer than retention."""

    days = max(1, int(retention_days))
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    rows = (
        (
            await db.execute(
                select(Project).where(
                    Project.status == PROJECT_STATUS_DELETION_PENDING,
                    Project.updated_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for project in rows:
        await _purge_project_rows(db, project, object_store=object_store)
        count += 1
    return count


async def leave_project(db: AsyncSession, *, project_id: str, user: User) -> bool:
    """A member leaves the project. The Primary Owner cannot leave."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None or not access.is_member:
        return False
    try:
        await ensure_not_last_owner(db, project_id=project_id, user_id=user.id, new_role=None)
    except ProjectAccessError:
        if is_primary_owner_role(access.role):
            raise ProjectAccessError("The Primary Owner cannot leave the project")
        raise ProjectAccessError("You are the last Owner and cannot leave the project")

    member = await db.get(ProjectMember, (project_id, user.id))
    if member is None:
        return False
    await db.delete(member)
    project = await db.get(Project, project_id)
    if project is not None:
        await bump_acl_version(db, project)
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="member.left",
        actor_user_id=user.id,
        payload={"user_id": user.id},
    )
    return True


# ---------------------------------------------------------------------------
# Membership management (Owner / Primary Owner)
# ---------------------------------------------------------------------------


async def _require_member_role_mutation(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    target: ProjectMember | None,
    new_role: str | None,
) -> None:
    """Enforce who may assign or change Owner-level membership.

    Caller must already have ``member.manage``. Primary Owner cannot be
    assigned through the API; only Primary Owner may add/change/remove Owners.
    """
    from fastapi import HTTPException, status

    if new_role == PROJECT_ROLE_PRIMARY_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The Primary Owner role cannot be assigned",
        )
    ensure_primary_owner_protected(target, new_role)
    needs_owner_manage = new_role == PROJECT_ROLE_OWNER or (target is not None and is_project_owner_role(target.role))
    if needs_owner_manage:
        await require_capability(db, project_id=project_id, user=user, capability="member.manage_owners")


async def list_members(db: AsyncSession, *, project_id: str, user: User) -> list[dict[str, Any]] | None:
    """Member roster. Members only: a public viewer gets 403, not the list."""
    await require_capability(db, project_id=project_id, user=user, capability="members.read")
    rows = (
        await db.execute(
            select(ProjectMember, User.username, User.display_name)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at)
        )
    ).all()
    return [_serialize_member(m, username=u, display_name=d) for m, u, d in rows]


async def add_member(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    target_user_id: int,
    role: str = PROJECT_ROLE_VIEWER,
) -> dict[str, Any]:
    """Primary Owner or Owner directly adds an existing active user as a member."""
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    normalized_role = validate_role(role)
    target = await db.get(User, target_user_id)
    if target is None or not target.is_active or target.deleted_at is not None:
        raise ProjectValidationError("User not found or inactive")

    existing = await db.get(ProjectMember, (project_id, target_user_id))
    await _require_member_role_mutation(db, project_id=project_id, user=user, target=existing, new_role=normalized_role)
    if existing is not None:
        if existing.role != normalized_role:
            await ensure_not_last_owner(db, project_id=project_id, user_id=target_user_id, new_role=normalized_role)
            existing.role = normalized_role
            existing.updated_at = datetime.datetime.utcnow()
        await db.flush()
        await append_project_audit(
            db,
            project_id=project_id,
            event_type="member.role_changed",
            actor_user_id=user.id,
            payload={"user_id": target_user_id, "role": normalized_role},
        )
        return _serialize_member(existing, username=target.username, display_name=target.display_name)

    member = ProjectMember(
        project_id=project_id,
        user_id=target_user_id,
        role=normalized_role,
        invited_by_user_id=user.id,
    )
    db.add(member)
    project = await db.get(Project, project_id)
    if project is not None:
        await bump_acl_version(db, project)
    await db.flush()
    await append_project_audit(
        db,
        project_id=project_id,
        event_type="member.added",
        actor_user_id=user.id,
        payload={"user_id": target_user_id, "role": normalized_role},
    )
    return _serialize_member(member, username=target.username, display_name=target.display_name)


async def update_member_role(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    target_user_id: int,
    role: str,
) -> dict[str, Any] | None:
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    normalized_role = validate_role(role)
    member = await db.get(ProjectMember, (project_id, target_user_id))
    if member is None:
        return None
    await _require_member_role_mutation(db, project_id=project_id, user=user, target=member, new_role=normalized_role)
    await ensure_not_last_owner(db, project_id=project_id, user_id=target_user_id, new_role=normalized_role)
    member.role = normalized_role
    member.updated_at = datetime.datetime.utcnow()
    project = await db.get(Project, project_id)
    if project is not None:
        await bump_acl_version(db, project)
    await db.flush()
    target = await db.get(User, target_user_id)
    await append_project_audit(
        db,
        project_id=project_id,
        event_type="member.role_changed",
        actor_user_id=user.id,
        payload={"user_id": target_user_id, "role": normalized_role},
    )
    return _serialize_member(
        member,
        username=target.username if target else None,
        display_name=target.display_name if target else None,
    )


async def remove_member(db: AsyncSession, *, project_id: str, user: User, target_user_id: int) -> bool:
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    member = await db.get(ProjectMember, (project_id, target_user_id))
    if member is None:
        return False
    await _require_member_role_mutation(db, project_id=project_id, user=user, target=member, new_role=None)
    await ensure_not_last_owner(db, project_id=project_id, user_id=target_user_id, new_role=None)
    await db.delete(member)
    project = await db.get(Project, project_id)
    if project is not None:
        await bump_acl_version(db, project)
    await db.flush()
    await append_project_audit(
        db,
        project_id=project_id,
        event_type="member.removed",
        actor_user_id=user.id,
        payload={"user_id": target_user_id},
    )
    return True


async def list_invitable_users(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    q: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]] | None:
    """Active users not already members — for the Owner invite picker."""
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    limit = max(1, min(limit, 50))
    member_ids_subq = (select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)).subquery()
    stmt = select(User.id, User.username, User.display_name).where(
        User.is_active.is_(True),
        User.deleted_at.is_(None),
        User.id.not_in(select(member_ids_subq.c.user_id)),
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.display_name.ilike(like)))
    stmt = stmt.order_by(User.username).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [{"id": r[0], "username": r[1], "displayName": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# Invitation links
# ---------------------------------------------------------------------------


def _serialize_invitation(inv: ProjectInvitation) -> dict[str, Any]:
    return {
        "id": inv.id,
        "projectId": inv.project_id,
        "role": inv.role,
        "maxUses": inv.max_uses,
        "useCount": inv.use_count,
        "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
        "createdByUserId": inv.created_by_user_id,
        "claimedByUserId": inv.claimed_by_user_id,
        "claimedAt": inv.claimed_at.isoformat() if inv.claimed_at else None,
        "revokedAt": inv.revoked_at.isoformat() if inv.revoked_at else None,
        "createdAt": inv.created_at.isoformat() if inv.created_at else None,
        "isExpired": (inv.expires_at < datetime.datetime.utcnow()) if inv.expires_at else False,
        "isRevoked": inv.revoked_at is not None,
        "isExhausted": inv.use_count >= inv.max_uses,
    }


async def create_invitation(
    db: AsyncSession,
    *,
    project_id: str,
    user: User,
    role: str = PROJECT_ROLE_VIEWER,
    max_uses: int = 1,
    ttl_days: int = INVITATION_DEFAULT_TTL_DAYS,
    notify_user_id: int | None = None,
) -> dict[str, Any]:
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    normalized_role = validate_invitation_role(role)
    max_uses = max(1, min(max_uses, 100))
    ttl_days = max(1, min(ttl_days, INVITATION_MAX_TTL_DAYS))

    token = secrets.token_urlsafe(32)
    invitation = ProjectInvitation(
        id=_new_id(),
        project_id=project_id,
        role=normalized_role,
        token_hash=_hash_token(token),
        max_uses=max_uses,
        use_count=0,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=ttl_days),
        created_by_user_id=user.id,
    )
    db.add(invitation)
    await db.flush()
    await append_project_audit(
        db,
        project_id=project_id,
        event_type="invitation.created",
        actor_user_id=user.id,
        payload={"role": normalized_role, "maxUses": max_uses, "ttlDays": ttl_days},
    )
    result = _serialize_invitation(invitation)
    result["token"] = token  # returned only once at creation time
    result["emailSent"] = False
    result["emailWarning"] = None
    if notify_user_id:
        await _maybe_email_invitation(
            db,
            result=result,
            token=token,
            notify_user_id=int(notify_user_id),
            actor=user,
            project=await db.get(Project, project_id),
            role=normalized_role,
        )
    return result


async def _maybe_email_invitation(
    db: AsyncSession,
    *,
    result: dict[str, Any],
    token: str,
    notify_user_id: int,
    actor: User,
    project: Project | None,
    role: str,
) -> None:
    """Best-effort invite email. Missing SMTP never fails invitation creation."""
    from app.config import get_settings
    from app.models.user import User as UserModel
    from app.services.smtp_service import SmtpNotConfiguredError, SmtpSendError, send_email

    if int(notify_user_id) == int(actor.id):
        result["emailWarning"] = "Email was not sent. Copy the invitation link."
        return
    recipient = await db.get(UserModel, notify_user_id)
    to_address = (getattr(recipient, "email", None) or "").strip() if recipient else ""
    if not to_address:
        result["emailWarning"] = "Email was not sent. Copy the invitation link."
        return
    base = (get_settings().frontend_url or "").rstrip("/")
    link = f"{base}/app/projects/invite?token={token}"
    project_name = (project.name if project is not None else "a project").strip() or "a project"
    body = (
        f"{actor.display_name or actor.username} invited you to join "
        f'"{project_name}" as {role}.\n\n'
        f"Open this link to accept:\n{link}\n"
    )
    try:
        await send_email(
            db,
            to_address=to_address,
            subject=f"Invitation to {project_name}",
            body_text=body,
        )
        result["emailSent"] = True
    except (SmtpNotConfiguredError, SmtpSendError):
        result["emailWarning"] = "Email was not sent. Copy the invitation link."


async def list_invitations(db: AsyncSession, *, project_id: str, user: User) -> list[dict[str, Any]] | None:
    """Pending invitations (tokens included) are for those who can manage members."""
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    rows = (
        (
            await db.execute(
                select(ProjectInvitation)
                .where(ProjectInvitation.project_id == project_id)
                .order_by(ProjectInvitation.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_invitation(i) for i in rows]


async def revoke_invitation(db: AsyncSession, *, project_id: str, invitation_id: str, user: User) -> bool:
    await require_capability(db, project_id=project_id, user=user, capability="member.manage")
    invitation = await db.get(ProjectInvitation, invitation_id)
    if invitation is None or invitation.project_id != project_id:
        return False
    if invitation.revoked_at is not None:
        return True
    invitation.revoked_at = datetime.datetime.utcnow()
    await db.flush()
    await append_project_audit(
        db,
        project_id=project_id,
        event_type="invitation.revoked",
        actor_user_id=user.id,
        payload={"invitationId": invitation_id},
    )
    return True


async def claim_invitation(db: AsyncSession, *, token: str, user: User) -> dict[str, Any] | None:
    """Claim an invitation link and join the project with the granted role."""
    token_hash = _hash_token(token)
    invitation = (
        (await db.execute(select(ProjectInvitation).where(ProjectInvitation.token_hash == token_hash)))
        .scalars()
        .first()
    )
    if invitation is None:
        return None
    now = datetime.datetime.utcnow()
    if invitation.revoked_at is not None:
        raise ProjectValidationError("Invitation has been revoked")
    if invitation.expires_at is not None and invitation.expires_at < now:
        raise ProjectValidationError("Invitation has expired")

    existing = await db.get(ProjectMember, (invitation.project_id, user.id))
    if existing is not None:
        # Already a member — idempotent claim; do not consume another use
        # (avoids exhausting a multi-use link on re-visits by the same user).
        invitation.claimed_by_user_id = user.id
        invitation.claimed_at = now
        await db.flush()
        project = await db.get(Project, invitation.project_id)
        return _serialize_project(project, role=existing.role, is_member=True) if project else None

    if invitation.use_count >= invitation.max_uses:
        raise ProjectValidationError("Invitation has been exhausted")

    member = ProjectMember(
        project_id=invitation.project_id,
        user_id=user.id,
        role=invitation.role,
        invited_by_user_id=invitation.created_by_user_id,
    )
    db.add(member)
    invitation.use_count = int(invitation.use_count) + 1
    invitation.claimed_by_user_id = user.id
    invitation.claimed_at = now
    project = await db.get(Project, invitation.project_id)
    if project is not None:
        await bump_acl_version(db, project)
    await db.flush()
    await append_project_audit(
        db,
        project_id=invitation.project_id,
        event_type="invitation.claimed",
        actor_user_id=user.id,
        payload={"invitationId": invitation.id, "role": invitation.role},
    )
    return _serialize_project(project, role=invitation.role, is_member=True) if project else None
