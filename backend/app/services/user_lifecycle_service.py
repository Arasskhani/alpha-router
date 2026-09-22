"""Soft delete, restore, and permanent removal of user accounts."""

from __future__ import annotations

import datetime

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import PlanAssignment
from app.models.logging import RequestLog
from app.models.user import User, UserRoleAssignment, user_group_members
from app.services.auth_events_service import method_for, record_auth_event
from app.services.user_account_cleanup_service import purge_user_account_data
from app.services.user_role_service import count_active_full_administrators, user_has_full_administrator

#: ``auth_provider`` of a purged row. Not a provider anyone can log in with,
#: which is the point: the row exists only to anchor audit references.
PURGED_AUTH_PROVIDER = "purged"


async def record_user_login(db: AsyncSession, user: User) -> None:
    user.last_login_at = datetime.datetime.utcnow()
    await db.flush()


async def soft_delete_user(db: AsyncSession, user: User) -> None:
    """Move the account to Deleted Users. Reversible, which is the point.

    Group memberships used to be deleted here. Nothing snapshotted them, so the
    deletion was not reversible at all: an LDAP user pruned by an OU change and
    picked up again by the next sync came back with no groups, and therefore no
    inherited budget plan, no group model access and no group knowledge or agent
    access - silently, and with no way to reconstruct what they had.

    The rows stay. ``app.services.group_membership`` is how "who is in this
    group" stays correctly answered while they do: a deleted account is not a
    member for any purpose a person or a bill can see.
    """

    user.deleted_at = datetime.datetime.utcnow()
    user.is_active = False
    # Sessions have to end now, not when the JWT expires.
    user.token_version = int(user.token_version or 0) + 1
    # No request in hand — a directory prune reaches here too — so the row
    # has no address, but it does say the sessions ended and why.
    await record_auth_event(
        event_type="session_revoked",
        user=user,
        reason_code="user_deleted",
        auth_method=method_for(user),
        db=db,
    )
    await db.flush()


async def restore_user(db: AsyncSession, user: User) -> None:
    """Bring an account back from Deleted Users, with everything it had."""

    if user.purged_at is not None:
        raise ValueError("Cannot restore a permanently deleted account")
    user.deleted_at = None
    user.is_active = True
    await db.flush()


async def restore_directory_user(db: AsyncSession, user: User) -> None:
    """Restore path used by LDAP sync when a user returns to the OU filter."""

    await restore_user(db, user)


async def permanently_delete_user(db: AsyncSession, user: User) -> None:
    """Remove the account and everything that identifies the person behind it.

    The ``users`` row itself survives, deliberately.

    ``agent_audit_events``, ``agent_tool_audit_events``,
    ``knowledge_audit_events`` and ``governance_audit_events`` all reference
    ``users.id`` with ``ON DELETE SET NULL``, and each carries a
    ``BEFORE UPDATE OR DELETE`` append-only trigger. PostgreSQL runs ``SET NULL``
    as a real UPDATE of the referencing row, so the trigger fires and raises
    ``audit table ... is append-only``: a plain ``DELETE FROM users`` cannot
    succeed for any administrator who has ever published an agent or touched a
    knowledge base.

    Weakening the constraint would be worse than the failure. The governance
    hash chain is computed over ``actor_user_id``, so nulling it would make
    every event by that actor fail verification - tamper-evidence reporting
    tampering that never happened.

    So the row is emptied instead: no name, no address, no credential, no
    directory identity, no session, no roles, no group membership. What is left
    is an opaque id that keeps the audit trail readable and verifiable.
    ``purged_at`` marks it, so neither user listing shows it again, and the
    username is released for re-use.
    """
    if await user_has_full_administrator(db, user.id) and await count_active_full_administrators(db) <= 1:
        raise ValueError("Cannot delete the last Full Administrator account")
    # The fields are about to be emptied; the snapshot has to be taken now
    # or the row would name nobody.
    await record_auth_event(
        event_type="session_revoked",
        user=user,
        reason_code="user_deleted",
        auth_method=method_for(user),
        db=db,
    )
    from app.models.api_key import UserApiKey

    user_id = user.id
    username = user.username
    await purge_user_account_data(db, user_id=user_id, username=username)
    await db.execute(update(RequestLog).where(RequestLog.user_id == user_id).values(user_id=None))
    await db.execute(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await db.execute(delete(PlanAssignment).where(PlanAssignment.user_id == user_id))
    await db.execute(delete(user_group_members).where(user_group_members.c.user_id == user_id))
    await db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id))

    now = datetime.datetime.utcnow()
    user.username = f"purged-user-{user_id}"
    user.email = None
    user.display_name = None
    user.hashed_password = None
    user.external_id = None
    user.auth_provider = PURGED_AUTH_PROVIDER
    for field in ("company", "job_title", "department", "office", "reporting_to"):
        setattr(user, field, None)
    user.totp_secret_encrypted = None
    user.totp_enabled = False
    user.totp_backup_codes_hashed = None
    user.last_login_at = None
    user.is_active = False
    user.deleted_at = user.deleted_at or now
    user.purged_at = now
    # Any JWT still in flight for this account stops working on the next request.
    user.token_version = int(user.token_version or 0) + 1
    await db.flush()


async def prune_sync_user(db: AsyncSession, user: User) -> str:
    """Move LDAP users outside the OU filter to Deleted Users (preserve data)."""
    if await user_has_full_administrator(db, user.id):
        return "skipped"
    if user.deleted_at is not None:
        return "skipped"
    await soft_delete_user(db, user)
    return "soft_deleted"
