"""FastAPI dependencies for auth and RBAC."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.rbac import (
    MenuKey,
    user_can_access_menu,
    user_has_agent_permission,
    user_can_write_menu,
    user_is_admin_panel,
)
from app.services.user_role_service import get_user_role_slugs

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve user from JWT. Inactive users remain authenticated (read-only chat/media/logs)."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name) if settings.enable_cookie_auth else None
    if not token and settings.allow_legacy_bearer_auth and creds:
        token = creds.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    username = payload.get("sub")
    user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account removed")
    # Revocation: reject tokens issued before the user's current token_version.
    # Tokens without ``ver`` (issued before this feature) are treated as 0,
    # which matches the default token_version for existing users — so they
    # keep working until the user re-logs in.
    jwt_ver = int(payload.get("ver", 0) or 0)
    if jwt_ver < int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked, please log in again")
    return user


async def require_active_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled. You can browse chat history and media, but cannot send new messages.",
        )
    return user


def _forbidden(detail: str = "Admin only") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_rbac_menu(menu: MenuKey, *, write: bool = False) -> Callable:
    async def _check(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
        slugs = await get_user_role_slugs(db, user.id)
        if not user_is_admin_panel(slugs):
            raise _forbidden()
        if not user.is_active:
            raise _forbidden("User inactive")
        if not user_can_access_menu(slugs, menu):
            raise _forbidden("Insufficient permissions for this menu")
        if write and not user_can_write_menu(slugs, menu):
            raise _forbidden("Read-only role: changes not allowed")
        return user

    return _check


def require_agent_permission(permission: str) -> Callable:
    """Require one action-level permission inside Agents & Knowledge."""

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not user.is_active:
            raise _forbidden("User inactive")
        slugs = await get_user_role_slugs(db, user.id)
        if not user_can_access_menu(slugs, "agents"):
            raise _forbidden("Insufficient permissions for Agents & Knowledge")
        if not user_has_agent_permission(slugs, permission):
            raise _forbidden(f"Missing Agent Platform permission: {permission}")
        return user

    return _check


async def require_admin(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    if not user.is_active:
        raise _forbidden("User inactive")
    slugs = await get_user_role_slugs(db, user.id)
    if not user_is_admin_panel(slugs):
        raise _forbidden()
    return user


async def require_super_admin(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    """Phase 9: gate destructive/rotation operations on the Super Admin role."""
    if not user.is_active:
        raise _forbidden("User inactive")
    slugs = await get_user_role_slugs(db, user.id)
    from app.services.rbac import user_has_super_admin_access

    if not user_has_super_admin_access(slugs):
        raise _forbidden("Super Admin only")
    return user


def _menu_requires(menu: MenuKey) -> tuple[Callable, Callable]:
    return require_rbac_menu(menu), require_rbac_menu(menu, write=True)


#: Menus whose pages contain an access-control editor. Each of them has to be
#: able to *read* the group and role directories to draw one, which is not the
#: same as being allowed to manage groups or roles.
ACL_EDITING_MENUS: tuple[MenuKey, ...] = ("users", "roles", "groups", "agents", "models", "chat_tools")


async def require_acl_directory(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    """Read the group and role directories, for any page that edits an ACL.

    The ACL editor offers a list of groups and a list of roles to grant to. It
    fetched both from endpoints gated on the Groups and Users menus, and
    swallowed the 403 - so an administrator holding, say, only the Chat Tools
    menu saw two empty dropdowns and no explanation, on Agent Studio and
    Knowledge Bases as much as here.

    Widening the read is the smaller evil: these are names and ids the grantee
    is about to be shown anyway, and the alternative is handing every operator
    who can grant anything the permission to manage groups.
    """
    slugs = await get_user_role_slugs(db, user.id)
    if not user_is_admin_panel(slugs):
        raise _forbidden()
    if not user.is_active:
        raise _forbidden("User inactive")
    if not any(user_can_access_menu(slugs, menu) for menu in ACL_EDITING_MENUS):
        raise _forbidden("Insufficient permissions for this menu")
    return user


async def require_role_catalog(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    """The role catalog, for the Users and Roles screens and every ACL editor."""
    return await require_acl_directory(user=user, db=db)


require_dashboard, require_dashboard_write = _menu_requires("dashboard")
require_chat, require_chat_write = _menu_requires("chat")
require_media, require_media_write = _menu_requires("media")
require_connections, require_connections_write = _menu_requires("connections")
require_models, require_models_write = _menu_requires("models")
require_api_keys, require_api_keys_write = _menu_requires("api_keys")
require_chat_tools, require_chat_tools_write = _menu_requires("chat_tools")
require_memory, require_memory_write = _menu_requires("memory")
require_roles, require_roles_write = _menu_requires("roles")
require_users, require_users_write = _menu_requires("users")
require_deleted_users, require_deleted_users_write = _menu_requires("deleted_users")
require_groups, require_groups_write = _menu_requires("groups")
require_plans, require_plans_write = _menu_requires("plans")
require_authentication, require_authentication_write = _menu_requires("authentication")
require_smtp, require_smtp_write = _menu_requires("smtp")
require_storage, require_storage_write = _menu_requires("storage")
require_reports, require_reports_write = _menu_requires("reports")
require_api_logs, require_api_logs_write = _menu_requires("api_logs")
require_operations, require_operations_write = _menu_requires("operations")
require_database, require_database_write = _menu_requires("database")
require_agents, require_agents_write = _menu_requires("agents")
require_admin_guide, require_admin_guide_write = _menu_requires("admin_guide")
require_user_manual, require_user_manual_write = _menu_requires("user_manual")
require_security_settings, require_security_settings_write = _menu_requires("security_settings")

# Backward-compatible category aliases (any menu in the group — prefer menu-specific deps in new code).
from app.services.rbac import MENUS_BY_CATEGORY  # noqa: E402


def require_rbac_category(category: str, *, write: bool = False) -> Callable:
    menus = MENUS_BY_CATEGORY.get(category, ())  # type: ignore[arg-type]

    async def _check(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
        slugs = await get_user_role_slugs(db, user.id)
        if not user_is_admin_panel(slugs):
            raise _forbidden()
        if not user.is_active:
            raise _forbidden("User inactive")
        if not any(user_can_access_menu(slugs, menu) for menu in menus):
            raise _forbidden("Insufficient permissions for this section")
        if write and not any(user_can_write_menu(slugs, menu) for menu in menus):
            raise _forbidden("Read-only role: changes not allowed")
        return user

    return _check


require_overview = require_rbac_category("overview")
require_overview_write = require_rbac_category("overview", write=True)
require_models_api = require_rbac_category("models_api")
require_models_api_write = require_rbac_category("models_api", write=True)
require_people_access = require_rbac_category("people_access")
require_people_access_write = require_rbac_category("people_access", write=True)
require_integrations = require_rbac_category("integrations")
require_integrations_write = require_rbac_category("integrations", write=True)
require_data_reports = require_rbac_category("data_reports")
require_data_reports_write = require_rbac_category("data_reports", write=True)
require_developer = require_rbac_category("developer")
require_developer_write = require_rbac_category("developer", write=True)
require_security = require_rbac_category("security")
require_security_write = require_rbac_category("security", write=True)


async def get_bearer_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name) if settings.enable_cookie_auth else None
    if not token and settings.allow_legacy_bearer_auth and creds:
        token = creds.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return token
