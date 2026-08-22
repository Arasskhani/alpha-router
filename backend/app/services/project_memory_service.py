"""Project memory: explicit, provenance-tracked facts scoped to a project.

Memory items are short durable facts that the Owner or an automated
extraction process can save for a project.  When the project's active
config has ``memory_enabled = True`` these facts are injected into the
system prompt for project-scoped chat turns.

Cross-project memory grants let a consumer project read *memory items*
(not raw chats or files) from a source project.  The grant is directional
and non-transitive.  Only a user who is Owner in *both* projects may
create or revoke a grant.
"""

from __future__ import annotations

import datetime
import hashlib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import (
    PROJECT_VISIBILITY_PRIVATE,
    Project,
    ProjectConfigVersion,
    ProjectMemory,
    ProjectMemoryGrant,
    ProjectMember,
)
from app.services.project_access_service import (
    ProjectAccess,
    append_project_audit,
    is_project_owner_role,
    require_capability,
    resolve_project_access,
)

MAX_MEMORY_CHARS = 500
MAX_MEMORIES_PER_PROJECT = 500
MAX_INJECT_ITEMS = 60
MAX_INJECT_CHARS = 8000
MAX_GRANT_RETRIEVAL_ITEMS = 20
MAX_GRANT_RETRIEVAL_CHARS = 3000

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ProjectMemoryValidationError(ValueError):
    """Invalid memory content."""


class ProjectMemoryLimitError(ValueError):
    """Project has reached the max number of memories."""


class ProjectMemoryNotFoundError(LookupError):
    """Memory missing or not owned by the project."""


class ProjectMemoryGrantError(ValueError):
    """Invalid cross-project memory grant."""


def normalize_memory_content(text: str | None) -> str:
    raw = "" if text is None else str(text)
    cleaned = _CONTROL_RE.sub("", raw)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        raise ProjectMemoryValidationError("Memory content is required")
    if len(cleaned) > MAX_MEMORY_CHARS:
        raise ProjectMemoryValidationError(
            f"Memory content exceeds {MAX_MEMORY_CHARS} characters"
        )
    return cleaned


def memory_content_hash(text: str) -> str:
    normalized = normalize_memory_content(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dt_to_iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value else None


def memory_to_client(row: ProjectMemory) -> dict:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "content": row.content,
        "sourceType": row.source_type,
        "sourceId": row.source_id,
        "authority": row.authority,
        "enabled": bool(row.enabled),
        "createdByUserId": row.created_by_user_id,
        "createdAt": _dt_to_iso(row.created_at),
        "updatedAt": _dt_to_iso(row.updated_at),
    }


def grant_to_client(row: ProjectMemoryGrant) -> dict:
    return {
        "id": row.id,
        "consumerProjectId": row.consumer_project_id,
        "sourceProjectId": row.source_project_id,
        "status": row.status,
        "revision": row.revision,
        "actorUserId": row.actor_user_id,
        "createdAt": _dt_to_iso(row.created_at),
        "updatedAt": _dt_to_iso(row.updated_at),
        "revokedAt": _dt_to_iso(row.revoked_at),
    }


# ---------------------------------------------------------------------------
# CRUD for project memory items
# ---------------------------------------------------------------------------


async def list_project_memories(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    include_disabled: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List memory items for a project (visible to any member)."""

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="project.view",
    )

    base = select(ProjectMemory).where(ProjectMemory.project_id == project_id)
    count_stmt = (
        select(func.count())
        .select_from(ProjectMemory)
        .where(ProjectMemory.project_id == project_id)
    )
    if not include_disabled:
        base = base.where(ProjectMemory.enabled.is_(True))
        count_stmt = count_stmt.where(ProjectMemory.enabled.is_(True))

    base = base.order_by(ProjectMemory.updated_at.desc(), ProjectMemory.id.desc())
    base = base.limit(limit).offset(offset)
    rows = (await db.execute(base)).scalars().all()
    total = (await db.execute(count_stmt)).scalar() or 0
    return [memory_to_client(row) for row in rows], total


async def _count_project_memories(db: AsyncSession, project_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ProjectMemory)
        .where(ProjectMemory.project_id == project_id)
    )
    return int(result.scalar_one() or 0)


async def create_project_memory(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    content: str,
    source_type: str = "manual",
    source_id: str | None = None,
) -> tuple[dict, bool]:
    """Create a memory item (Owner or Contributor with memory.manage)."""

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="memory.manage",
    )

    normalized = normalize_memory_content(content)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    existing = (
        await db.execute(
            select(ProjectMemory).where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.content_hash == digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return memory_to_client(existing), False

    if await _count_project_memories(db, project_id) >= MAX_MEMORIES_PER_PROJECT:
        raise ProjectMemoryLimitError(
            f"Memory limit of {MAX_MEMORIES_PER_PROJECT} reached for this project"
        )

    now = datetime.datetime.utcnow()
    row = ProjectMemory(
        id=str(uuid.uuid4()),
        project_id=project_id,
        content=normalized,
        content_hash=digest,
        source_type=(source_type or "manual")[:32],
        source_id=source_id[:128] if source_id else None,
        authority="user",
        enabled=True,
        created_by_user_id=access.user_id,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raced = (
            await db.execute(
                select(ProjectMemory).where(
                    ProjectMemory.project_id == project_id,
                    ProjectMemory.content_hash == digest,
                )
            )
        ).scalar_one_or_none()
        if raced is None:
            raise
        return memory_to_client(raced), False

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.memory.created",
        actor_user_id=access.user_id,
        payload={"memory_id": row.id, "source_type": row.source_type},
    )
    return memory_to_client(row), True


async def _get_project_memory(
    db: AsyncSession,
    project_id: str,
    memory_id: str,
) -> ProjectMemory:
    row = await db.get(ProjectMemory, memory_id)
    if row is None or row.project_id != project_id:
        raise ProjectMemoryNotFoundError("Memory not found")
    return row


async def update_project_memory(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    memory_id: str,
    content: str | None = None,
    enabled: bool | None = None,
) -> dict:
    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="memory.manage",
    )
    row = await _get_project_memory(db, project_id, memory_id)
    changed = False
    if content is not None:
        normalized = normalize_memory_content(content)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest != row.content_hash:
            conflict = (
                await db.execute(
                    select(ProjectMemory).where(
                        ProjectMemory.project_id == project_id,
                        ProjectMemory.content_hash == digest,
                        ProjectMemory.id != row.id,
                    )
                )
            ).scalar_one_or_none()
            if conflict is not None:
                raise ProjectMemoryValidationError(
                    "Another memory with the same content already exists"
                )
            row.content = normalized
            row.content_hash = digest
            changed = True
    if enabled is not None:
        next_enabled = bool(enabled)
        if next_enabled != bool(row.enabled):
            row.enabled = next_enabled
            changed = True
    if changed:
        row.updated_at = datetime.datetime.utcnow()
        await db.flush()
    return memory_to_client(row)


async def delete_project_memory(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    memory_id: str,
) -> None:
    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="memory.manage",
    )
    row = await _get_project_memory(db, project_id, memory_id)
    await db.delete(row)
    await db.flush()
    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.memory.deleted",
        actor_user_id=access.user_id,
        payload={"memory_id": memory_id},
    )


# ---------------------------------------------------------------------------
# Cross-project memory grants
# ---------------------------------------------------------------------------


async def _is_owner(db: AsyncSession, project_id: str, user_id: int) -> bool:
    member = await db.get(ProjectMember, (project_id, user_id))
    return member is not None and is_project_owner_role(member.role)


async def list_memory_grants(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
) -> list[dict]:
    """List all grants where this project is the consumer (Owner only)."""

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="memory.grant",
    )
    rows = (
        await db.execute(
            select(ProjectMemoryGrant)
            .where(
                ProjectMemoryGrant.consumer_project_id == project_id,
                ProjectMemoryGrant.status == "active",
            )
            .order_by(ProjectMemoryGrant.created_at.desc())
        )
    ).scalars().all()
    return [grant_to_client(row) for row in rows]


async def create_memory_grant(
    db: AsyncSession,
    *,
    consumer_project_id: str,
    source_project_id: str,
    user: object,
) -> dict:
    """Grant consumer project read access to source project's memory items.

    Requires the caller to be Owner in *both* projects.
    """

    if consumer_project_id == source_project_id:
        raise ProjectMemoryGrantError("Cannot grant memory access to the same project")

    access = await require_capability(
        db,
        project_id=consumer_project_id,
        user=user,
        capability="memory.grant",
    )

    if not await _is_owner(db, source_project_id, access.user_id):
        raise ProjectMemoryGrantError(
            "You must be an Owner of the source project to grant access to its memory"
        )

    # Check the source project exists and is accessible.
    source_project = await db.get(Project, source_project_id)
    if source_project is None or source_project.status != "active":
        raise ProjectMemoryGrantError("Source project is not available")

    existing = (
        await db.execute(
            select(ProjectMemoryGrant).where(
                ProjectMemoryGrant.consumer_project_id == consumer_project_id,
                ProjectMemoryGrant.source_project_id == source_project_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status == "active":
            return grant_to_client(existing)
        # Re-activate a previously revoked grant.
        existing.status = "active"
        existing.revoked_at = None
        existing.revision += 1
        existing.updated_at = datetime.datetime.utcnow()
        await db.flush()
        grant = existing
    else:
        grant = ProjectMemoryGrant(
            id=str(uuid.uuid4()),
            consumer_project_id=consumer_project_id,
            source_project_id=source_project_id,
            actor_user_id=access.user_id,
            status="active",
            revision=1,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow(),
        )
        db.add(grant)
        await db.flush()

    await append_project_audit(
        db,
        project_id=consumer_project_id,
        event_type="project.memory.grant.created",
        actor_user_id=access.user_id,
        payload={
            "grant_id": grant.id,
            "source_project_id": source_project_id,
        },
    )
    return grant_to_client(grant)


async def revoke_memory_grant(
    db: AsyncSession,
    *,
    consumer_project_id: str,
    source_project_id: str,
    user: object,
) -> bool:
    """Revoke a cross-project memory grant (Owner of consumer project)."""

    access = await require_capability(
        db,
        project_id=consumer_project_id,
        user=user,
        capability="memory.grant",
    )

    grant = (
        await db.execute(
            select(ProjectMemoryGrant).where(
                ProjectMemoryGrant.consumer_project_id == consumer_project_id,
                ProjectMemoryGrant.source_project_id == source_project_id,
                ProjectMemoryGrant.status == "active",
            )
        )
    ).scalar_one_or_none()

    if grant is None:
        return False

    grant.status = "revoked"
    grant.revoked_at = datetime.datetime.utcnow()
    grant.revision += 1
    grant.updated_at = datetime.datetime.utcnow()
    await db.flush()

    await append_project_audit(
        db,
        project_id=consumer_project_id,
        event_type="project.memory.grant.revoked",
        actor_user_id=access.user_id,
        payload={"grant_id": grant.id, "source_project_id": source_project_id},
    )
    return True


# ---------------------------------------------------------------------------
# Memory injection for AI turns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectMemoryInjection:
    """Resolved memory facts ready for system-prompt injection."""

    own_facts: tuple[str, ...]
    granted_facts: tuple[str, ...]
    total_facts: int


async def _load_enabled_memories(
    db: AsyncSession,
    project_id: str,
    *,
    max_items: int,
    max_chars: int,
) -> list[str]:
    rows = (
        await db.execute(
            select(ProjectMemory)
            .where(
                ProjectMemory.project_id == project_id,
                ProjectMemory.enabled.is_(True),
            )
            .order_by(ProjectMemory.updated_at.desc(), ProjectMemory.id.desc())
            .limit(max_items)
        )
    ).scalars().all()

    facts: list[str] = []
    total_chars = 0
    for row in rows:
        text = (row.content or "").strip()
        if not text:
            continue
        cost = len(text) + 2
        if total_chars + cost > max_chars:
            break
        facts.append(text)
        total_chars += cost
    return facts


async def _load_granted_memories(
    db: AsyncSession,
    consumer_project_id: str,
    *,
    max_items: int,
    max_chars: int,
) -> list[str]:
    """Load memory items from source projects via active grants.

    Each source project contributes up to ``max_items // grant_count`` items
    so that retrieval stays bounded regardless of how many grants exist.
    """

    grants = (
        await db.execute(
            select(ProjectMemoryGrant).where(
                ProjectMemoryGrant.consumer_project_id == consumer_project_id,
                ProjectMemoryGrant.status == "active",
            )
        )
    ).scalars().all()

    if not grants:
        return []

    per_grant_items = max(1, max_items // max(1, len(grants)))
    facts: list[str] = []
    total_chars = 0
    for grant in grants:
        rows = (
            await db.execute(
                select(ProjectMemory)
                .where(
                    ProjectMemory.project_id == grant.source_project_id,
                    ProjectMemory.enabled.is_(True),
                )
                .order_by(ProjectMemory.updated_at.desc(), ProjectMemory.id.desc())
                .limit(per_grant_items)
            )
        ).scalars().all()
        for row in rows:
            text = (row.content or "").strip()
            if not text:
                continue
            cost = len(text) + 2
            if total_chars + cost > max_chars:
                break
            facts.append(text)
            total_chars += cost
    return facts


async def load_injectable_project_memories(
    db: AsyncSession,
    *,
    project_id: str,
    memory_enabled: bool,
) -> ProjectMemoryInjection:
    """Resolve all injectable memory facts for a project-scoped turn.

    When ``memory_enabled`` is False, returns empty facts.
    """

    if not memory_enabled:
        return ProjectMemoryInjection(
            own_facts=(), granted_facts=(), total_facts=0
        )

    own_facts = await _load_enabled_memories(
        db,
        project_id,
        max_items=MAX_INJECT_ITEMS,
        max_chars=MAX_INJECT_CHARS,
    )

    granted_facts = await _load_granted_memories(
        db,
        project_id,
        max_items=MAX_GRANT_RETRIEVAL_ITEMS,
        max_chars=MAX_GRANT_RETRIEVAL_CHARS,
    )

    return ProjectMemoryInjection(
        own_facts=tuple(own_facts),
        granted_facts=tuple(granted_facts),
        total_facts=len(own_facts) + len(granted_facts),
    )


def format_project_memory_block(injection: ProjectMemoryInjection) -> str:
    """Format memory facts as a system-prompt block."""

    lines = [
        "## Project memory",
        "The following are durable facts saved for this project. Use them when relevant.",
        "Do not invent extra facts. Chat messages remain the primary conversation context.",
    ]
    for fact in injection.own_facts:
        lines.append(f"- {fact}")
    if injection.granted_facts:
        lines.append("")
        lines.append(
            "## Cross-project memory (read-only grants)"
        )
        lines.append(
            "The following facts come from other projects via memory grants. "
            "Use them as supplementary context only."
        )
        for fact in injection.granted_facts:
            lines.append(f"- {fact}")
    return "\n".join(lines)
