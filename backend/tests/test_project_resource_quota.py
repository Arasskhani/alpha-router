"""The 20-file project resource limit is real, not just printed in the UI.

``MAX_PROJECT_RESOURCE_UPLOAD_FILES = 20`` in projectsApi.ts was advertised to
the user and enforced nowhere on the server. ``upload_project_resource`` had no
count quota, no byte quota and no rate limit, so one authenticated account could
create unlimited projects and fill each with unlimited files - and every upload
runs ClamAV, a sandboxed parse, OCR, chunking and an embedding pass, so the cost
is real even before storage. Project *media* has enforced a quota all along;
resources were the gap.
"""

from __future__ import annotations

import pytest

from app.core.security import hash_password
from app.models.knowledge import KnowledgeBase, KnowledgeDocument
from app.models.project import PROJECT_RESOURCE_STATUS_ACTIVE, PROJECT_RESOURCE_STATUS_REVOKED, ProjectResource
from app.models.user import User
from app.services.project_resource_service import (
    PROJECT_RESOURCE_MAX_FILES,
    ProjectResourceQuotaError,
    count_project_resources,
    ensure_project_resource_quota,
)
from app.services.project_service import create_project


async def _project_with(db_session, *, active: int, revoked: int = 0) -> str:
    owner = User(
        username=f"quota_owner_{active}_{revoked}",
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(owner)
    await db_session.flush()
    project = await create_project(db_session, user=owner, name="Resourceful")
    project_id = project["id"]

    base = KnowledgeBase(id=f"kb-{project_id}", name="Project KB", slug=f"kb-{project_id}")
    db_session.add(base)
    await db_session.flush()

    for index in range(active + revoked):
        db_session.add(
            KnowledgeDocument(
                id=f"doc-{project_id}-{index}",
                knowledge_base_id=base.id,
                canonical_key=f"file-{index}.pdf",
                title=f"file-{index}.pdf",
            )
        )
        db_session.add(
            ProjectResource(
                id=f"res-{project_id}-{index}",
                project_id=project_id,
                document_id=f"doc-{project_id}-{index}",
                title=f"file-{index}.pdf",
                status=PROJECT_RESOURCE_STATUS_ACTIVE if index < active else PROJECT_RESOURCE_STATUS_REVOKED,
            )
        )
    await db_session.flush()
    return project_id


async def test_an_empty_project_accepts_an_upload(db_session):
    project_id = await _project_with(db_session, active=0)
    await ensure_project_resource_quota(db_session, project_id)


async def test_one_below_the_limit_still_accepts(db_session):
    project_id = await _project_with(db_session, active=PROJECT_RESOURCE_MAX_FILES - 1)
    await ensure_project_resource_quota(db_session, project_id)


async def test_at_the_limit_the_next_upload_is_refused(db_session):
    project_id = await _project_with(db_session, active=PROJECT_RESOURCE_MAX_FILES)

    with pytest.raises(ProjectResourceQuotaError) as exc:
        await ensure_project_resource_quota(db_session, project_id)
    assert exc.value.limit == PROJECT_RESOURCE_MAX_FILES
    assert str(PROJECT_RESOURCE_MAX_FILES) in str(exc.value)


async def test_a_revoked_resource_gives_its_slot_back(db_session):
    project_id = await _project_with(db_session, active=PROJECT_RESOURCE_MAX_FILES - 1, revoked=5)

    assert await count_project_resources(db_session, project_id) == PROJECT_RESOURCE_MAX_FILES - 1
    await ensure_project_resource_quota(db_session, project_id)


async def test_the_server_limit_matches_what_the_ui_advertises():
    """The two numbers have to be the same one, or the UI is lying again."""

    import pathlib
    import re

    api = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "projectsApi.ts"
    match = re.search(r"MAX_PROJECT_RESOURCE_UPLOAD_FILES\s*=\s*(\d+)", api.read_text(encoding="utf-8"))
    assert match, "the UI constant is gone; keep the two in step"
    assert int(match.group(1)) == PROJECT_RESOURCE_MAX_FILES


async def test_the_check_runs_before_the_ingestion_pipeline():
    """Refusing after ClamAV, OCR and embedding means paying for a rejected upload."""

    import inspect

    from app.services import project_resource_service

    source = inspect.getsource(project_resource_service.upload_project_resource)
    assert source.index("ensure_project_resource_quota") < source.index("submit_document_bytes")
