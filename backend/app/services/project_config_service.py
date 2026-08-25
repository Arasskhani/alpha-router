"""Project configuration versioning — immutable snapshots of Advanced settings.

Each edit creates a *new* ``ProjectConfigVersion`` row and points the
project's ``active_config_version_id`` at it.  Old versions remain for
reproducibility and audit.  Only the Owner may change configuration.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import (
    Project,
    ProjectConfigVersion,
)
from app.services.project_access_service import (
    append_project_audit,
    require_capability,
)

MAX_CUSTOM_PROMPT_CHARS = 12_000
MAX_GROUNDING_POLICY_KEYS = 32


@dataclass(frozen=True)
class ProjectConfigSnapshot:
    """Read-only view of the active config for a project."""

    config_version_id: str | None
    revision: int
    custom_prompt: str | None
    memory_enabled: bool
    memory_auto_capture: bool
    grounding_policy: dict
    created_at: str | None


def _validate_custom_prompt(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    if len(cleaned) > MAX_CUSTOM_PROMPT_CHARS:
        raise ValueError(
            f"Custom prompt exceeds {MAX_CUSTOM_PROMPT_CHARS} characters"
        )
    return cleaned or None


def _validate_grounding_policy(policy: dict | None) -> dict:
    if policy is None:
        return {}
    if not isinstance(policy, dict):
        raise ValueError("Grounding policy must be a JSON object")
    if len(policy) > MAX_GROUNDING_POLICY_KEYS:
        raise ValueError(
            f"Grounding policy exceeds {MAX_GROUNDING_POLICY_KEYS} keys"
        )
    # Shallow-copy and ensure all keys/values are JSON-serialisable.
    try:
        return json.loads(json.dumps(policy, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("Grounding policy contains non-serialisable values") from exc


def config_to_client(row: ProjectConfigVersion) -> dict:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "revision": row.revision,
        "customPrompt": row.custom_prompt,
        "memoryEnabled": bool(row.memory_enabled),
        "memoryAutoCapture": bool(row.memory_auto_capture),
        "groundingPolicy": dict(row.grounding_policy or {}),
        "createdByUserId": row.created_by_user_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


async def get_active_config(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
) -> ProjectConfigSnapshot | None:
    """Return the active config snapshot for a project (visible to any member)."""

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="project.view",
    )
    project = await db.get(Project, project_id)
    if project is None:
        return None

    version = (
        await db.get(ProjectConfigVersion, project.active_config_version_id)
        if project.active_config_version_id is not None
        else None
    )
    if version is None:
        return ProjectConfigSnapshot(
            config_version_id=None,
            revision=0,
            custom_prompt=None,
            memory_enabled=True,
            memory_auto_capture=True,
            grounding_policy={},
            created_at=None,
        )

    return ProjectConfigSnapshot(
        config_version_id=version.id,
        revision=version.revision,
        custom_prompt=version.custom_prompt,
        memory_enabled=bool(version.memory_enabled),
        memory_auto_capture=bool(version.memory_auto_capture),
        grounding_policy=dict(version.grounding_policy or {}),
        created_at=version.created_at.isoformat() if version.created_at else None,
    )


async def update_project_config(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    custom_prompt: str | None = None,
    memory_enabled: bool = True,
    memory_auto_capture: bool = True,
    grounding_policy: dict | None = None,
) -> ProjectConfigVersion:
    """Create a new immutable config version and activate it (Owner only)."""

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="project.edit",
    )
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")

    prompt = _validate_custom_prompt(custom_prompt)
    policy = _validate_grounding_policy(grounding_policy)

    next_revision = (
        int(
            (
                await db.execute(
                    select(func.max(ProjectConfigVersion.revision)).where(
                        ProjectConfigVersion.project_id == project_id
                    )
                )
            ).scalar()
            or 0
        )
        + 1
    )

    version = ProjectConfigVersion(
        id=str(uuid.uuid4()),
        project_id=project_id,
        revision=next_revision,
        custom_prompt=prompt,
        memory_enabled=bool(memory_enabled),
        memory_auto_capture=bool(memory_auto_capture),
        grounding_policy=policy,
        created_by_user_id=access.user_id,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(version)
    await db.flush()

    project.active_config_version_id = version.id
    project.updated_at = datetime.datetime.utcnow()
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.config.updated",
        actor_user_id=access.user_id,
        payload={
            "config_version_id": version.id,
            "revision": next_revision,
            "memory_enabled": bool(memory_enabled),
            "memory_auto_capture": bool(memory_auto_capture),
            "custom_prompt_set": prompt is not None,
            "grounding_policy_keys": list(policy.keys()),
        },
    )

    return version


async def load_project_memory_flags(
    db: AsyncSession, project_id: str
) -> tuple[bool, bool]:
    """(memory_enabled, memory_auto_capture) with no ACL check, for background jobs."""

    project = await db.get(Project, project_id)
    if project is None or not project.active_config_version_id:
        return True, True
    version = await db.get(ProjectConfigVersion, project.active_config_version_id)
    if version is None:
        return True, True
    return bool(version.memory_enabled), bool(version.memory_auto_capture)


async def list_config_versions(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List config version history (Owner only — sensitive content)."""

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="project.edit",
    )

    base = (
        select(ProjectConfigVersion)
        .where(ProjectConfigVersion.project_id == project_id)
        .order_by(ProjectConfigVersion.revision.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(base)).scalars().all()

    count_stmt = (
        select(func.count())
        .select_from(ProjectConfigVersion)
        .where(ProjectConfigVersion.project_id == project_id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    return [config_to_client(row) for row in rows], total
