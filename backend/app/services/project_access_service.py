"""Centralized access control for the Projects domain.

All project-scoped routes, downloads, background jobs, and streams must
resolve capabilities through this service.  Client-supplied project IDs
and roles are never trusted; membership is always re-read from the
database at the time of the authorization check.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import (
    PROJECT_OWNER_ROLES,
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_ROLES,
    PROJECT_STATUS_ACTIVE,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectAuditEvent,
    ProjectMember,
)

Capability = Literal[
    "project.view",
    # Read capabilities. Every *member* role has all of them; the implicit
    # viewer a public project grants to any active user gets only the ones in
    # PUBLIC_VIEWER_CAPABILITIES. Making a project public is meant to share its
    # chats and knowledge, not its memory, media library, member list or
    # custom prompt.
    "chat.read",
    "resource.read",
    "memory.read",
    "media.read",
    "members.read",
    "config.read",
    "project.edit",
    "project.delete",
    "member.manage",
    "member.manage_owners",
    "resource.upload",
    "resource.manage",
    "chat.write",
    "chat.pin",
    "memory.manage",
    "memory.grant",
    "media.upload",
    "media.delete",
]


def is_project_owner_role(role: str | None) -> bool:
    """True for Primary Owner and Owner — the two management roles."""
    return role in PROJECT_OWNER_ROLES


def is_primary_owner_role(role: str | None) -> bool:
    return role == PROJECT_ROLE_PRIMARY_OWNER


MEMBER_READ_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        "project.view",
        "chat.read",
        "resource.read",
        "memory.read",
        "media.read",
        "members.read",
        "config.read",
    }
)
PUBLIC_VIEWER_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        "project.view",
        "chat.read",
        "resource.read",
    }
)

# Capabilities granted per role. Primary Owner is a strict superset of Owner.
_OWNER_CAPABILITIES: frozenset[Capability] = MEMBER_READ_CAPABILITIES | frozenset(
    {
        "project.edit",
        "member.manage",
        "resource.upload",
        "resource.manage",
        "chat.write",
        "chat.pin",
        "memory.manage",
        "memory.grant",
        "media.upload",
        "media.delete",
    }
)
_CAPABILITIES: dict[str, frozenset[Capability]] = {
    PROJECT_ROLE_PRIMARY_OWNER: _OWNER_CAPABILITIES
    | frozenset({"project.delete", "member.manage_owners"}),
    PROJECT_ROLE_OWNER: _OWNER_CAPABILITIES,
    PROJECT_ROLE_CONTRIBUTOR: MEMBER_READ_CAPABILITIES
    | frozenset(
        {
            "resource.upload",
            "chat.write",
            "chat.pin",
            "media.upload",
            "media.delete",
        }
    ),
    PROJECT_ROLE_VIEWER: MEMBER_READ_CAPABILITIES,
}


@dataclass(frozen=True)
class ProjectAccess:
    """Resolved access decision for one user against one project."""

    project_id: str
    user_id: int | None
    role: str | None  # explicit role, or "viewer" for implicit public access
    is_member: bool
    is_public_viewer: bool

    @property
    def capabilities(self) -> frozenset[Capability]:
        if self.is_public_viewer:
            return PUBLIC_VIEWER_CAPABILITIES
        role = self.role
        if role is None:
            return frozenset()
        return _CAPABILITIES.get(role, frozenset())

    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities


class ProjectAccessError(Exception):
    """Raised when a membership invariant would be violated."""


async def resolve_project_access(
    db: AsyncSession,
    *,
    project_id: str,
    user: object | None,
) -> ProjectAccess | None:
    """Resolve the effective access for *user* against *project_id*.

    Returns ``None`` when the project does not exist or is deletion-pending
    and the caller is not a member (hide existence → 404 semantics).
    """
    project = await db.get(Project, project_id)
    if project is None:
        return None

    user_id = getattr(user, "id", None)
    is_active = bool(getattr(user, "is_active", False))
    deleted = getattr(user, "deleted_at", None) is not None

    # Inactive or deleted users never get project access.
    if user_id is None or not is_active or deleted:
        return None

    member = await db.get(ProjectMember, (project_id, user_id))
    if member is not None:
        return ProjectAccess(
            project_id=project_id,
            user_id=user_id,
            role=member.role,
            is_member=True,
            is_public_viewer=False,
        )

    # Archived and deletion-pending projects hide from non-members.
    if project.status != PROJECT_STATUS_ACTIVE:
        return None

    if project.visibility == PROJECT_VISIBILITY_PUBLIC:
        return ProjectAccess(
            project_id=project_id,
            user_id=user_id,
            role=PROJECT_ROLE_VIEWER,
            is_member=False,
            is_public_viewer=True,
        )

    return None


async def require_capability(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    capability: Capability,
) -> ProjectAccess:
    """Resolve access and raise 404/403 for insufficient callers.

    - Non-existent or hidden project → 404 (existence is hidden).
    - Member lacking the capability → 403.
    """
    from fastapi import HTTPException, status

    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if not access.can(capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission for this action",
        )
    return access


async def count_owners(db: AsyncSession, project_id: str) -> int:
    """Count Primary Owner and Owner members (management roles)."""
    result = await db.execute(
        select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.role.in_(PROJECT_OWNER_ROLES),
        )
    )
    return int(result.scalar_one() or 0)


async def count_primary_owners(db: AsyncSession, project_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.role == PROJECT_ROLE_PRIMARY_OWNER,
        )
    )
    return int(result.scalar_one() or 0)


def assignable_roles_for(actor_role: str | None) -> frozenset[str]:
    """Roles an actor may grant. Primary Owner is never assignable via API."""
    if actor_role == PROJECT_ROLE_PRIMARY_OWNER:
        return frozenset({PROJECT_ROLE_OWNER, PROJECT_ROLE_CONTRIBUTOR, PROJECT_ROLE_VIEWER})
    if actor_role == PROJECT_ROLE_OWNER:
        return frozenset({PROJECT_ROLE_CONTRIBUTOR, PROJECT_ROLE_VIEWER})
    return frozenset()


def ensure_primary_owner_protected(member: ProjectMember | None, new_role: str | None) -> None:
    """The Primary Owner cannot be demoted, removed, or overwritten."""
    if member is None or not is_primary_owner_role(member.role):
        return
    if new_role == PROJECT_ROLE_PRIMARY_OWNER:
        return
    raise ProjectAccessError("Cannot remove or change the Primary Owner")


async def ensure_not_last_owner(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: int,
    new_role: str | None,
) -> None:
    """Raise ProjectAccessError if the Primary Owner would disappear.

    Regular Owners may be demoted or removed whenever a Primary Owner remains.
    If a project has no Primary Owner (legacy), the last Owner-role member is
    still protected.
    """
    member = await db.get(ProjectMember, (project_id, user_id))
    ensure_primary_owner_protected(member, new_role)
    if member is None or not is_project_owner_role(member.role):
        return
    if is_project_owner_role(new_role):
        return
    if await count_primary_owners(db, project_id) >= 1:
        return
    if await count_owners(db, project_id) <= 1:
        raise ProjectAccessError("Cannot remove or demote the last project Owner")


async def append_project_audit(
    db: AsyncSession,
    *,
    project_id: str | None,
    event_type: str,
    actor_user_id: int | None,
    outcome: str = "success",
    payload: dict | None = None,
) -> ProjectAuditEvent:
    """Append one immutable audit event for a project action."""
    event = ProjectAuditEvent(
        id=str(uuid.uuid4()),
        project_id=project_id,
        event_type=event_type,
        actor_user_id=actor_user_id,
        outcome=outcome,
        payload_json=payload or {},
        created_at=datetime.datetime.utcnow(),
    )
    db.add(event)
    await db.flush()
    return event


async def bump_acl_version(db: AsyncSession, project: Project) -> int:
    """Increment the project's ACL version, invalidating cached access decisions."""
    project.acl_version = int(project.acl_version or 1) + 1
    project.updated_at = datetime.datetime.utcnow()
    return project.acl_version


def validate_role(role: str) -> str:
    """Normalize and validate a project role string."""
    normalized = (role or "").strip().lower()
    if normalized not in PROJECT_ROLES:
        raise ValueError(f"Invalid project role: {role!r}")
    return normalized


def validate_invitation_role(role: str) -> str:
    """Validate that an invitation role is never Owner or Primary Owner."""
    normalized = validate_role(role)
    if is_project_owner_role(normalized):
        raise ValueError("Invitation links cannot grant Owner or Primary Owner")
    return normalized


async def can_view_project_activity(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
) -> bool:
    """Primary Owner/Owner, or an admin with the Reports menu, may view Activity."""
    from app.services.rbac import user_can_access_menu
    from app.services.user_role_service import get_user_role_slugs

    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is not None and is_project_owner_role(access.role) and access.is_member:
        return True
    project = await db.get(Project, project_id)
    if project is None:
        return False
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    slugs = await get_user_role_slugs(db, int(user_id))
    return user_can_access_menu(slugs, "reports")
