"""Project chat and resource API — shared workspaces scoped to a project."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import (
    _activity_export_response,
    _activity_query_filters,
    _build_scoped_activity,
    activity_explore_opts,
)
from app.api.deps import get_bearer_token, get_current_user, require_active_user
from app.config import get_settings
from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.services import activity_service
from app.services.attachment_policy import media_response_type_and_disposition
from app.services.bounded_io import BoundedIOError, read_upload_bounded
from app.services.project_access_service import (
    ProjectAccessError,
    can_view_project_activity,
    resolve_project_access,
)
from app.services.project_chat_service import (
    append_project_chat_message,
    create_project_chat_session,
    delete_project_chat_session,
    get_last_opened_session_id,
    get_project_chat_session,
    list_pinned_chats,
    list_project_chat_messages,
    list_project_chat_sessions,
    pin_project_chat,
    sync_project_chats,
    touch_project_visit,
    unpin_project_chat,
)
from app.services.project_composer_pref_service import (
    get_project_chat_composer_prefs,
    upsert_project_chat_composer_prefs,
)
from app.services.project_config_service import (
    get_active_config,
    list_config_versions,
    update_project_config,
)
from app.services.project_media_service import (
    ProjectMediaQuotaError,
    ProjectMediaValidationError,
    default_project_media_store,
    delete_project_media,
    get_project_media,
    list_project_media,
    read_project_media_bytes,
    upload_project_media,
)
from app.services.project_memory_service import (
    ProjectMemoryLimitError,
    ProjectMemoryNotFoundError,
    ProjectMemoryValidationError,
    create_memory_grant,
    create_project_memory,
    delete_all_auto_project_memories,
    delete_project_memory,
    export_project_memories,
    list_memory_grants,
    list_project_memories,
    revoke_memory_grant,
    update_project_memory,
)
from app.services.project_resource_service import (
    ProjectResourceQuotaError,
    delete_project_resource,
    get_project_resource,
    list_project_resources,
    upload_project_resource,
)
from app.services.project_room_service import (
    append_project_room_message,
    create_project_room,
    create_room_handoff,
    delete_project_room,
    delete_project_room_message,
    get_project_room,
    list_project_room_messages,
    list_project_rooms,
    sync_project_rooms,
    update_project_room_message,
)
from app.services.project_service import (
    ProjectValidationError,
    add_member,
    archive_project,
    claim_invitation,
    create_invitation,
    create_project,
    delete_project,
    get_project,
    get_project_overview,
    hard_delete_project,
    leave_project,
    list_invitable_users,
    list_invitations,
    list_members,
    list_my_projects,
    list_public_projects,
    list_recent_projects,
    remove_member,
    restore_project,
    revoke_invitation,
    update_member_role,
    update_project,
)
from app.services.storage_service import media_input_limit
from app.services.upload_screening import UploadRejected, screen_upload
from app.services.user_role_service import primary_role_for_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Project CRUD + membership + invitations
# ---------------------------------------------------------------------------


class ProjectCreateIn(BaseModel):
    name: str = Field(..., max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    visibility: str = Field(default="private")


class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    visibility: str | None = None
    # Required (must equal the current project name) when switching to public.
    confirm_public_name: str | None = Field(default=None, max_length=255)


class MemberRoleIn(BaseModel):
    role: str


class AddMemberIn(BaseModel):
    userId: int
    role: str = "viewer"


class InvitationCreateIn(BaseModel):
    role: str = "viewer"
    maxUses: int = Field(default=1, ge=1, le=100)
    ttlDays: int = Field(default=7, ge=1, le=30)
    notifyUserId: int | None = None


class ClaimInvitationIn(BaseModel):
    token: str


class ProjectPrefsIn(BaseModel):
    lastOpenedSessionId: str | None = None


@router.get("")
async def list_projects_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scope: str = Query("mine", pattern="^(mine|explore|recent)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
) -> dict[str, Any]:
    if scope == "explore":
        rows, total = await list_public_projects(db, user=user, limit=limit, offset=offset, q=q)
    elif scope == "recent":
        rows, total = await list_recent_projects(db, user=user, limit=min(limit, 20))
    else:
        rows, total = await list_my_projects(db, user=user, limit=limit, offset=offset)
    return {"projects": rows, "total": total}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    body: ProjectCreateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        project = await create_project(
            db,
            user=user,
            name=body.name,
            description=body.description,
            visibility=body.visibility,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return project


@router.get("/{project_id}")
async def get_project_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await get_project(db, project_id=project_id, user=user)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    await touch_project_visit(db, project_id=project_id, user=user)
    await db.commit()
    return project


@router.get("/{project_id}/overview")
async def get_project_overview_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    overview = await get_project_overview(db, project_id=project_id, user=user)
    if overview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return overview


@router.put("/{project_id}/prefs")
async def put_project_prefs(
    project_id: str,
    body: ProjectPrefsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await touch_project_visit(
            db,
            project_id=project_id,
            user=user,
            session_id=body.lastOpenedSessionId,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    await db.commit()
    return result


async def _require_project_activity(db: AsyncSession, *, project_id: str, user: User) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if await can_view_project_activity(db, project_id=project_id, user=user):
        return project
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the project Owner can view Activity",
    )


@router.get("/{project_id}/activity")
async def project_activity(
    project_id: str,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    explore: dict = Depends(activity_explore_opts),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await _require_project_activity(db, project_id=project_id, user=user)
    filters = _activity_query_filters(model_id=model_id, username=username, app=app, response_status=response_status)
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        project_id=project.id,
    )
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "project": {"id": project.id, "name": project.name, "status": project.status},
        "scope": "project",
        "model_id": filters["model_id"],
        "filters": filters,
    }


@router.get("/{project_id}/activity/export")
async def project_activity_export(
    project_id: str,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    jwt_token: str = Depends(get_bearer_token),
):
    project = await _require_project_activity(db, project_id=project_id, user=user)
    filters = _activity_query_filters(model_id=model_id, username=username, app=app, response_status=response_status)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-project-{project.id}-activity-{period}",
        scope="project",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, user.id),
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        project_id=project.id,
    )


@router.put("/{project_id}")
async def update_project_endpoint(
    project_id: str,
    body: ProjectUpdateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        project = await update_project(
            db,
            project_id=project_id,
            user=user,
            name=body.name,
            description=body.description,
            visibility=body.visibility,
            confirm_public_name=body.confirm_public_name,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return project


@router.delete("/{project_id}")
async def delete_project_endpoint(
    project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        deleted = await delete_project(db, project_id=project_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"deleted": True}


@router.post("/{project_id}/archive")
async def archive_project_endpoint(
    project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        project = await archive_project(db, project_id=project_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("/{project_id}/restore")
async def restore_project_endpoint(
    project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        project = await restore_project(db, project_id=project_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("/{project_id}/purge")
async def purge_project_endpoint(
    project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        purged = await hard_delete_project(db, project_id=project_id, user=user, require_pending=True)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not purged:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"purged": True}


@router.post("/{project_id}/leave")
async def leave_project_endpoint(
    project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        left = await leave_project(db, project_id=project_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectAccessError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not left:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"left": True}


@router.get("/{project_id}/members")
async def list_members_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    members = await list_members(db, project_id=project_id, user=user)
    if members is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"members": members}


@router.post("/{project_id}/members")
async def add_member_endpoint(
    project_id: str,
    body: AddMemberIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        member = await add_member(db, project_id=project_id, user=user, target_user_id=body.userId, role=body.role)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectAccessError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return member


@router.patch("/{project_id}/members/{user_id}")
async def update_member_endpoint(
    project_id: str,
    user_id: int,
    body: MemberRoleIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        member = await update_member_role(db, project_id=project_id, user=user, target_user_id=user_id, role=body.role)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectAccessError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return member


@router.delete("/{project_id}/members/{user_id}")
async def remove_member_endpoint(
    project_id: str,
    user_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        removed = await remove_member(db, project_id=project_id, user=user, target_user_id=user_id)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectAccessError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return {"removed": True}


@router.get("/{project_id}/invitable-users")
async def list_invitable_users_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    users = await list_invitable_users(db, project_id=project_id, user=user, q=q, limit=limit)
    if users is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"users": users}


@router.get("/{project_id}/invitations")
async def list_invitations_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    invitations = await list_invitations(db, project_id=project_id, user=user)
    if invitations is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"invitations": invitations}


@router.post("/{project_id}/invitations")
async def create_invitation_endpoint(
    project_id: str,
    body: InvitationCreateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        invitation = await create_invitation(
            db,
            project_id=project_id,
            user=user,
            role=body.role,
            max_uses=body.maxUses,
            ttl_days=body.ttlDays,
            notify_user_id=body.notifyUserId,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return invitation


@router.delete("/{project_id}/invitations/{invitation_id}")
async def revoke_invitation_endpoint(
    project_id: str,
    invitation_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        revoked = await revoke_invitation(db, project_id=project_id, invitation_id=invitation_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return {"revoked": True}


@router.post("/invitations/claim")
async def claim_invitation_endpoint(
    body: ClaimInvitationIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        project = await claim_invitation(db, token=body.token, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return project


class ProjectChatCreateIn(BaseModel):
    id: str | None = None
    title: str = "New chat"
    model: str = ""


class ProjectChatComposerPrefsIn(BaseModel):
    tools: dict[str, Any] = Field(default_factory=dict)
    toolsTouched: bool = False
    model: str | None = None
    selectedAgentSlug: str | None = None


class ProjectChatMessageIn(BaseModel):
    role: str = Field(..., max_length=16)
    content: str
    clientMessageId: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


@router.get("/{project_id}/chats")
async def get_project_chats(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
) -> dict[str, Any]:
    result = await list_project_chat_sessions(db, project_id=project_id, user=user, limit=limit, offset=offset, q=q)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    sessions, total = result
    pinned = await list_pinned_chats(db, project_id=project_id, user=user)
    last_opened = await get_last_opened_session_id(db, project_id=project_id, user=user)
    return {
        "sessions": sessions,
        "total": total,
        "pinnedSessionIds": pinned or [],
        "lastOpenedSessionId": last_opened,
    }


@router.get("/{project_id}/chats/sync")
async def sync_project_chats_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    since: int | None = Query(None, ge=0),
    session_id: str | None = Query(None),
    after_sequence: int | None = Query(None, ge=0),
) -> dict[str, Any]:
    result = await sync_project_chats(
        db,
        project_id=project_id,
        user=user,
        since_ms=since,
        session_id=session_id,
        after_sequence=after_sequence,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result


@router.post("/{project_id}/chats")
async def create_project_chat(
    project_id: str,
    body: ProjectChatCreateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        session = await create_project_chat_session(
            db,
            project_id=project_id,
            user=user,
            title=body.title,
            model_id=body.model,
            session_id=body.id,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return session


@router.get("/{project_id}/chats/{session_id}")
async def get_project_chat(
    project_id: str,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    session = await get_project_chat_session(db, project_id=project_id, session_id=session_id, user=user)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return session


@router.get("/{project_id}/chats/{session_id}/composer-prefs")
async def get_project_chat_composer_prefs_endpoint(
    project_id: str,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await get_project_chat_composer_prefs(db, project_id=project_id, session_id=session_id, user=user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return result


@router.put("/{project_id}/chats/{session_id}/composer-prefs")
async def put_project_chat_composer_prefs_endpoint(
    project_id: str,
    session_id: str,
    body: ProjectChatComposerPrefsIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await upsert_project_chat_composer_prefs(
            db,
            project_id=project_id,
            session_id=session_id,
            user=user,
            payload=body.model_dump(),
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    await db.commit()
    return result


@router.delete("/{project_id}/chats/{session_id}")
async def delete_project_chat(
    project_id: str,
    session_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await delete_project_chat_session(db, project_id=project_id, session_id=session_id, user=user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return {"deleted": True}


@router.get("/{project_id}/chats/{session_id}/messages")
async def get_project_chat_messages(
    project_id: str,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=200),
    before: int | None = Query(None),
) -> dict[str, Any]:
    result = await list_project_chat_messages(
        db,
        project_id=project_id,
        session_id=session_id,
        user=user,
        limit=limit,
        before=before,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    messages, has_more = result
    return {"messages": messages, "hasMore": has_more, "has_more": has_more}


@router.post("/{project_id}/chats/{session_id}/messages")
async def post_project_chat_message(
    project_id: str,
    session_id: str,
    body: ProjectChatMessageIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    message = await append_project_chat_message(
        db,
        project_id=project_id,
        session_id=session_id,
        user=user,
        role=body.role,
        content=body.content,
        client_message_id=body.clientMessageId,
        meta=body.meta,
    )
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return message


@router.post("/{project_id}/chats/{session_id}/pin")
async def pin_chat(
    project_id: str,
    session_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await pin_project_chat(db, project_id=project_id, session_id=session_id, user=user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return result


@router.delete("/{project_id}/chats/{session_id}/pin")
async def unpin_chat(
    project_id: str,
    session_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await unpin_project_chat(db, project_id=project_id, session_id=session_id, user=user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    return result


class ProjectRoomCreateIn(BaseModel):
    id: str | None = None
    title: str = "New room"


class ProjectRoomMessageIn(BaseModel):
    content: str
    clientMessageId: str | None = None
    replyToMessageId: str | None = None


class ProjectRoomMessageEditIn(BaseModel):
    content: str = Field(..., min_length=1)


class ProjectRoomHandoffIn(BaseModel):
    title: str | None = None
    brief: str = Field(..., min_length=1, max_length=8000)


@router.get("/{project_id}/rooms")
async def get_project_rooms(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
) -> dict[str, Any]:
    result = await list_project_rooms(db, project_id=project_id, user=user, limit=limit, offset=offset, q=q)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    rooms, total = result
    return {"rooms": rooms, "total": total}


@router.get("/{project_id}/rooms/sync")
async def sync_project_rooms_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    since: int | None = Query(None, ge=0),
    session_id: str | None = Query(None),
    after_sequence: int | None = Query(None, ge=0),
) -> dict[str, Any]:
    result = await sync_project_rooms(
        db,
        project_id=project_id,
        user=user,
        since_ms=since,
        session_id=session_id,
        after_sequence=after_sequence,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result


@router.post("/{project_id}/rooms")
async def create_project_room_endpoint(
    project_id: str,
    body: ProjectRoomCreateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        room = await create_project_room(
            db,
            project_id=project_id,
            user=user,
            title=body.title,
            session_id=body.id,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return room


@router.get("/{project_id}/rooms/{room_id}")
async def get_project_room_endpoint(
    project_id: str,
    room_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    room = await get_project_room(db, project_id=project_id, room_id=room_id, user=user)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return room


@router.delete("/{project_id}/rooms/{room_id}")
async def delete_project_room_endpoint(
    project_id: str,
    room_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await delete_project_room(db, project_id=project_id, room_id=room_id, user=user)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return {"deleted": True}


@router.get("/{project_id}/rooms/{room_id}/messages")
async def get_project_room_messages(
    project_id: str,
    room_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=200),
    before: int | None = Query(None),
) -> dict[str, Any]:
    result = await list_project_room_messages(
        db,
        project_id=project_id,
        room_id=room_id,
        user=user,
        limit=limit,
        before=before,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    messages, has_more = result
    return {"messages": messages, "hasMore": has_more, "has_more": has_more}


@router.post("/{project_id}/rooms/{room_id}/messages")
async def post_project_room_message(
    project_id: str,
    room_id: str,
    body: ProjectRoomMessageIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    message = await append_project_room_message(
        db,
        project_id=project_id,
        room_id=room_id,
        user=user,
        content=body.content,
        client_message_id=body.clientMessageId,
        reply_to_message_id=body.replyToMessageId,
    )
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return message


@router.patch("/{project_id}/rooms/{room_id}/messages/{message_id}")
async def patch_project_room_message(
    project_id: str,
    room_id: str,
    message_id: str,
    body: ProjectRoomMessageEditIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        message = await update_project_room_message(
            db,
            project_id=project_id,
            room_id=room_id,
            message_id=message_id,
            user=user,
            content=body.content,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return message


@router.delete("/{project_id}/rooms/{room_id}/messages/{message_id}")
async def delete_project_room_message_endpoint(
    project_id: str,
    room_id: str,
    message_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await delete_project_room_message(
        db,
        project_id=project_id,
        room_id=room_id,
        message_id=message_id,
        user=user,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return {"deleted": True}


@router.post("/{project_id}/rooms/{room_id}/handoffs")
async def post_project_room_handoff(
    project_id: str,
    room_id: str,
    body: ProjectRoomHandoffIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await create_room_handoff(
            db,
            project_id=project_id,
            room_id=room_id,
            user=user,
            brief=body.brief,
            title=body.title,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return result


# ---------------------------------------------------------------------------
# Project resources — file uploads by Owner/Contributor.
# ---------------------------------------------------------------------------


@router.get("/{project_id}/resources")
async def get_project_resources(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    resource_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = await list_project_resources(
        db,
        project_id=project_id,
        user=user,
        status=resource_status,
        limit=limit,
        offset=offset,
    )
    return {"resources": items, "total": total}


@router.get("/{project_id}/resources/{resource_id}")
async def get_project_resource_endpoint(
    project_id: str,
    resource_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    resource = await get_project_resource(db, project_id=project_id, resource_id=resource_id, user=user)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return resource


@router.post("/{project_id}/resources", status_code=status.HTTP_202_ACCEPTED)
async def upload_project_resource_endpoint(
    project_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        data = await read_upload_bounded(
            file,
            max_bytes=get_settings().knowledge_max_upload_bytes,
        )
        result = await upload_project_resource(
            db,
            project_id=project_id,
            user=user,
            file_name=file.filename or "resource",
            declared_mime=file.content_type,
            data=data,
            title=title,
        )
        await db.commit()
    except ProjectResourceQuotaError as exc:
        # Before ValueError, which it is: a quota answer is 413, not 400.
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except (BoundedIOError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Resource storage is unavailable",
        ) from exc
    return {
        "resourceId": result.resource.id,
        "documentId": result.submission.document.id,
        "documentVersionId": result.submission.version.id,
        "jobId": result.submission.job.id if result.submission.job else None,
        "duplicate": result.submission.duplicate,
        "status": result.resource.status,
    }


@router.delete("/{project_id}/resources/{resource_id}")
async def delete_project_resource_endpoint(
    project_id: str,
    resource_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        deleted = await delete_project_resource(db, project_id=project_id, resource_id=resource_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Resource deletion failed",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Project media — binary assets owned by the project.
# ---------------------------------------------------------------------------


@router.get("/{project_id}/media")
async def list_project_media_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    kind: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = await list_project_media(
        db,
        project_id=project_id,
        user=user,
        kind=kind,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.post("/{project_id}/media", status_code=status.HTTP_201_CREATED)
async def upload_project_media_endpoint(
    project_id: str,
    file: UploadFile = File(...),
    kind: str | None = Form(default=None),
    source_model: str | None = Form(default=None),
    source_prompt: str | None = Form(default=None),
    chat_session_id: str | None = Form(default=None),
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        data = await read_upload_bounded(file, max_bytes=media_input_limit())
        await screen_upload(data, file.filename or "upload")
        item = await upload_project_media(
            db,
            project_id=project_id,
            user=user,
            file_name=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            content_bytes=data,
            kind=kind,
            source_model=source_model,
            source_prompt=source_prompt,
            chat_session_id=chat_session_id,
            object_store=default_project_media_store(),
        )
        await db.commit()
    except UploadRejected as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except (BoundedIOError, ProjectMediaValidationError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProjectMediaQuotaError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media storage is unavailable",
        ) from exc
    return item


@router.get("/{project_id}/media/{media_id}")
async def get_project_media_endpoint(
    project_id: str,
    media_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    item = await get_project_media(db, project_id=project_id, media_id=media_id, user=user)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    return item


@router.get("/{project_id}/media/{media_id}/download")
async def download_project_media_endpoint(
    project_id: str,
    media_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        result = await read_project_media_bytes(
            db,
            project_id=project_id,
            media_id=media_id,
            user=user,
            object_store=default_project_media_store(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media not found",
        ) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    row, blob = result
    # Personal media has gone through this pair since it shipped; project media
    # replayed the client's Content-Type and marked anything image/* inline, so
    # an SVG containing a script executed on the application's own origin.
    media_type, disposition = media_response_type_and_disposition(
        file_name=row.file_name or "download",
        kind=row.kind,
        stored_mime=row.mime_type,
    )
    return Response(content=blob, media_type=media_type, headers={"Content-Disposition": disposition})


@router.delete("/{project_id}/media/{media_id}")
async def delete_project_media_endpoint(
    project_id: str,
    media_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        deleted = await delete_project_media(
            db,
            project_id=project_id,
            media_id=media_id,
            user=user,
            object_store=default_project_media_store(),
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media deletion failed",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Project configuration (Advanced settings — Owner only)
# ---------------------------------------------------------------------------


class ProjectConfigIn(BaseModel):
    customPrompt: str | None = Field(default=None, max_length=12000)
    memoryEnabled: bool = True
    memoryAutoCapture: bool = True
    groundingPolicy: dict[str, Any] = Field(default_factory=dict)


@router.get("/{project_id}/config")
async def get_project_config(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    config = await get_active_config(db, project_id=project_id, user=user)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {
        "configVersionId": config.config_version_id,
        "revision": config.revision,
        "customPrompt": config.custom_prompt,
        "memoryEnabled": config.memory_enabled,
        "memoryAutoCapture": config.memory_auto_capture,
        "groundingPolicy": config.grounding_policy,
        "createdAt": config.created_at,
    }


@router.put("/{project_id}/config")
async def update_project_config_endpoint(
    project_id: str,
    body: ProjectConfigIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        version = await update_project_config(
            db,
            project_id=project_id,
            user=user,
            custom_prompt=body.customPrompt,
            memory_enabled=body.memoryEnabled,
            memory_auto_capture=body.memoryAutoCapture,
            grounding_policy=body.groundingPolicy,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "configVersionId": version.id,
        "revision": version.revision,
        "memoryEnabled": bool(version.memory_enabled),
        "memoryAutoCapture": bool(version.memory_auto_capture),
        "customPrompt": version.custom_prompt,
        "groundingPolicy": dict(version.grounding_policy or {}),
    }


@router.get("/{project_id}/config/versions")
async def get_project_config_versions(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    versions, total = await list_config_versions(db, project_id=project_id, user=user, limit=limit, offset=offset)
    return {"versions": versions, "total": total}


# ---------------------------------------------------------------------------
# Project memory
# ---------------------------------------------------------------------------


class ProjectMemoryIn(BaseModel):
    content: str = Field(..., max_length=500)
    sourceType: str = Field(default="manual", max_length=32)
    sourceId: str | None = Field(default=None, max_length=128)


class ProjectMemoryUpdateIn(BaseModel):
    content: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


@router.get("/{project_id}/memories")
async def get_project_memories(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    include_disabled: bool = Query(True),
    origin: str | None = Query(None, pattern="^(manual|auto|auto_chat)$"),
    category: str | None = Query(None, max_length=32),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items, total = await list_project_memories(
        db,
        project_id=project_id,
        user=user,
        include_disabled=include_disabled,
        origin=origin,
        category=category,
        limit=limit,
        offset=offset,
    )
    return {"memories": items, "total": total}


@router.get("/{project_id}/memories/export")
async def export_project_memories_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items = await export_project_memories(db, project_id=project_id, user=user)
    return {"memories": items, "total": len(items)}


@router.delete("/{project_id}/memories")
async def delete_all_auto_project_memories_endpoint(
    project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        deleted = await delete_all_auto_project_memories(db, project_id=project_id, user=user)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    return {"deleted": deleted}


@router.post("/{project_id}/memories")
async def create_project_memory_endpoint(
    project_id: str,
    body: ProjectMemoryIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        memory, created = await create_project_memory(
            db,
            project_id=project_id,
            user=user,
            content=body.content,
            source_type=body.sourceType,
            source_id=body.sourceId,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except (ProjectMemoryValidationError, ProjectMemoryLimitError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {**memory, "created": created}


@router.patch("/{project_id}/memories/{memory_id}")
async def update_project_memory_endpoint(
    project_id: str,
    memory_id: str,
    body: ProjectMemoryUpdateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        memory = await update_project_memory(
            db,
            project_id=project_id,
            user=user,
            memory_id=memory_id,
            content=body.content,
            enabled=body.enabled,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectMemoryNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProjectMemoryValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return memory


@router.delete("/{project_id}/memories/{memory_id}")
async def delete_project_memory_endpoint(
    project_id: str,
    memory_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await delete_project_memory(db, project_id=project_id, user=user, memory_id=memory_id)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ProjectMemoryNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Cross-project memory grants (Owner only)
# ---------------------------------------------------------------------------


class MemoryGrantIn(BaseModel):
    sourceProjectId: str


@router.get("/{project_id}/memory-grants")
async def get_memory_grants(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    grants = await list_memory_grants(db, project_id=project_id, user=user)
    return {"grants": grants}


@router.post("/{project_id}/memory-grants")
async def create_memory_grant_endpoint(
    project_id: str,
    body: MemoryGrantIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        grant = await create_memory_grant(
            db,
            consumer_project_id=project_id,
            source_project_id=body.sourceProjectId,
            user=user,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return grant


@router.delete("/{project_id}/memory-grants/{source_project_id}")
async def revoke_memory_grant_endpoint(
    project_id: str,
    source_project_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        revoked = await revoke_memory_grant(
            db,
            consumer_project_id=project_id,
            source_project_id=source_project_id,
            user=user,
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")
    return {"revoked": True}
