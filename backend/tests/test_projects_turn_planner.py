"""ProjectTurnPlanner injects prompt/memory/resources only for authorized project sessions."""

import asyncio
import datetime
import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion
from app.models.project import (
    PROJECT_RESOURCE_STATUS_ACTIVE,
    PROJECT_RESOURCE_STATUS_PROCESSING,
    PROJECT_RESOURCE_STATUS_REVOKED,
    PROJECT_ROLE_PRIMARY_OWNER,
    Project,
    ProjectMember,
    ProjectResource,
)
from app.models.user import User
from app.services.knowledge_crypto_service import encrypt_text
from app.services.project_config_service import update_project_config
from app.services.project_memory_service import create_memory_grant, create_project_memory
from app.services.project_resource_service import ensure_project_knowledge_base
from app.services.project_turn_planner import plan_project_turn

PROJ = "proj-turn-1"
PROJ_SRC = "proj-turn-src"


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _setup(db):
    owner = await _user(db, "owner")
    outsider = await _user(db, "outsider")
    db.add(
        Project(
            id=PROJ,
            name="Turn",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    await db.flush()
    return owner, outsider


async def _chat(db, user, *, project_id=None, sid="sess-turn"):
    now = datetime.datetime.utcnow()
    row = ChatSession(
        id=sid,
        user_id=user.id,
        title="T",
        model_id="",
        tools={},
        private_mode=False,
        project_id=project_id,
        created_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return row


def _user_messages(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def _joined(messages: list[dict]) -> str:
    parts: list[str] = []
    for item in messages:
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def test_personal_chat_has_no_project_prompt():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                await update_project_config(
                    db,
                    project_id=PROJ,
                    user=owner,
                    custom_prompt="Always greet as ProjectBot.",
                    memory_enabled=True,
                )
                personal = await _chat(db, owner, project_id=None, sid="personal-1")
                out = await plan_project_turn(
                    db,
                    _user_messages("hello"),
                    user_id=owner.id,
                    chat_session_id=personal.id,
                    client_project_id=PROJ,
                )
                blob = _joined(out)
                assert "Project instructions" not in blob
                assert "ProjectBot" not in blob
                assert "Project memory" not in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_custom_prompt_injected():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                await update_project_config(
                    db,
                    project_id=PROJ,
                    user=owner,
                    custom_prompt="Always greet as ProjectBot.",
                    memory_enabled=True,
                )
                session = await _chat(db, owner, project_id=PROJ)
                out = await plan_project_turn(
                    db,
                    _user_messages("hello"),
                    user_id=owner.id,
                    chat_session_id=session.id,
                )
                blob = _joined(out)
                assert out[0]["role"] == "system"
                assert "Project instructions" in blob
                assert "Always greet as ProjectBot." in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_memory_disabled_skips_facts():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                await create_project_memory(
                    db,
                    project_id=PROJ,
                    user=owner,
                    content="The mascot is a blue fox.",
                )
                await update_project_config(
                    db,
                    project_id=PROJ,
                    user=owner,
                    custom_prompt="Stay concise.",
                    memory_enabled=False,
                )
                session = await _chat(db, owner, project_id=PROJ)
                out = await plan_project_turn(
                    db,
                    _user_messages("what is the mascot?"),
                    user_id=owner.id,
                    chat_session_id=session.id,
                )
                blob = _joined(out)
                assert "Stay concise." in blob
                assert "Project memory" not in blob
                assert "blue fox" not in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_granted_memory_injected():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                db.add(
                    Project(
                        id=PROJ_SRC,
                        name="Source",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(
                    ProjectMember(
                        project_id=PROJ_SRC,
                        user_id=owner.id,
                        role=PROJECT_ROLE_PRIMARY_OWNER,
                    )
                )
                await db.flush()
                await create_project_memory(
                    db,
                    project_id=PROJ_SRC,
                    user=owner,
                    content="Source brand color is teal.",
                )
                await create_memory_grant(
                    db,
                    consumer_project_id=PROJ,
                    source_project_id=PROJ_SRC,
                    user=owner,
                )
                session = await _chat(db, owner, project_id=PROJ)
                out = await plan_project_turn(
                    db,
                    _user_messages("what color?"),
                    user_id=owner.id,
                    chat_session_id=session.id,
                )
                blob = _joined(out)
                assert "Cross-project memory" in blob
                assert "Source brand color is teal." in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_resource_grounding_uses_project_kb():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                project = await db.get(Project, PROJ)
                kb = await ensure_project_knowledge_base(db, project=project)
                assert kb.slug.startswith("project-internal-")
                document = KnowledgeDocument(
                    id=str(uuid.uuid4()),
                    knowledge_base_id=kb.id,
                    canonical_key="onboarding.txt",
                    title="Onboarding",
                    status="active",
                )
                version = KnowledgeDocumentVersion(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    version_number=1,
                    status="published",
                    storage_key=f"private/knowledge/documents/{document.id}",
                    file_name="onboarding.txt",
                    mime_type="text/plain",
                    size_bytes=40,
                    sha256=hashlib.sha256(b"onboarding").hexdigest(),
                    language="en",
                    classification="internal",
                    authority="canonical",
                )
                db.add_all([document, version])
                await db.flush()
                chunk_id = str(uuid.uuid4())
                text = "The refund window is fourteen days after delivery."
                db.add(
                    KnowledgeChunk(
                        id=chunk_id,
                        document_version_id=version.id,
                        chunk_index=0,
                        content=encrypt_text(
                            text,
                            associated_data=f"knowledge-chunk:{chunk_id}",
                        ),
                        content_hash=hashlib.sha256(f"0\0{text}".encode()).hexdigest(),
                        token_count=8,
                        page_number=1,
                        section="Refunds",
                        language="en",
                        metadata_json={"kind": "leaf"},
                    )
                )
                db.add(
                    ProjectResource(
                        id=str(uuid.uuid4()),
                        project_id=PROJ,
                        document_id=document.id,
                        title="Onboarding guide",
                        status=PROJECT_RESOURCE_STATUS_ACTIVE,
                        uploaded_by_user_id=owner.id,
                    )
                )
                await db.flush()
                session = await _chat(db, owner, project_id=PROJ)
                out = await plan_project_turn(
                    db,
                    _user_messages("What is the refund window after delivery?"),
                    user_id=owner.id,
                    chat_session_id=session.id,
                )
                blob = _joined(out)
                assert "Project resources" in blob
                assert "fourteen days" in blob
                assert "Onboarding guide" in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_resource_grounding_uses_published_version_not_row_status():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                project = await db.get(Project, PROJ)
                kb = await ensure_project_knowledge_base(db, project=project)
                document = KnowledgeDocument(
                    id=str(uuid.uuid4()),
                    knowledge_base_id=kb.id,
                    canonical_key="policy.txt",
                    title="Policy",
                    status="active",
                )
                version = KnowledgeDocumentVersion(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    version_number=1,
                    status="published",
                    storage_key=f"private/knowledge/documents/{document.id}",
                    file_name="policy.txt",
                    mime_type="text/plain",
                    size_bytes=40,
                    sha256=hashlib.sha256(b"policy").hexdigest(),
                    language="en",
                    classification="internal",
                    authority="canonical",
                )
                db.add_all([document, version])
                await db.flush()
                chunk_id = str(uuid.uuid4())
                text = "The office badge code is seven two one."
                db.add(
                    KnowledgeChunk(
                        id=chunk_id,
                        document_version_id=version.id,
                        chunk_index=0,
                        content=encrypt_text(
                            text,
                            associated_data=f"knowledge-chunk:{chunk_id}",
                        ),
                        content_hash=hashlib.sha256(f"0\0{text}".encode()).hexdigest(),
                        token_count=8,
                        page_number=1,
                        section="Access",
                        language="en",
                        metadata_json={"kind": "leaf"},
                    )
                )
                db.add(
                    ProjectResource(
                        id=str(uuid.uuid4()),
                        project_id=PROJ,
                        document_id=document.id,
                        title="Access policy",
                        status=PROJECT_RESOURCE_STATUS_PROCESSING,
                        uploaded_by_user_id=owner.id,
                    )
                )
                await db.flush()
                session = await _chat(db, owner, project_id=PROJ)
                out = await plan_project_turn(
                    db,
                    _user_messages("What is the office badge code?"),
                    user_id=owner.id,
                    chat_session_id=session.id,
                )
                blob = _joined(out)
                assert "Project resources" in blob
                assert "seven two one" in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_revoked_resource_is_not_grounded():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _ = await _setup(db)
                project = await db.get(Project, PROJ)
                kb = await ensure_project_knowledge_base(db, project=project)
                document = KnowledgeDocument(
                    id=str(uuid.uuid4()),
                    knowledge_base_id=kb.id,
                    canonical_key="secret.txt",
                    title="Secret",
                    status="active",
                )
                version = KnowledgeDocumentVersion(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    version_number=1,
                    status="published",
                    storage_key=f"private/knowledge/documents/{document.id}",
                    file_name="secret.txt",
                    mime_type="text/plain",
                    size_bytes=20,
                    sha256=hashlib.sha256(b"secret").hexdigest(),
                    language="en",
                    classification="internal",
                    authority="canonical",
                )
                db.add_all([document, version])
                await db.flush()
                chunk_id = str(uuid.uuid4())
                text = "The vault combination is nine nine."
                db.add(
                    KnowledgeChunk(
                        id=chunk_id,
                        document_version_id=version.id,
                        chunk_index=0,
                        content=encrypt_text(
                            text,
                            associated_data=f"knowledge-chunk:{chunk_id}",
                        ),
                        content_hash=hashlib.sha256(f"0\0{text}".encode()).hexdigest(),
                        token_count=6,
                        page_number=1,
                        section="Vault",
                        language="en",
                        metadata_json={"kind": "leaf"},
                    )
                )
                db.add(
                    ProjectResource(
                        id=str(uuid.uuid4()),
                        project_id=PROJ,
                        document_id=document.id,
                        title="Vault note",
                        status=PROJECT_RESOURCE_STATUS_REVOKED,
                        uploaded_by_user_id=owner.id,
                    )
                )
                await db.flush()
                session = await _chat(db, owner, project_id=PROJ)
                out = await plan_project_turn(
                    db,
                    _user_messages("What is the vault combination?"),
                    user_id=owner.id,
                    chat_session_id=session.id,
                )
                blob = _joined(out)
                assert "nine nine" not in blob
                assert "Project resources" not in blob
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_outsider_session_cannot_spoof_project_id():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, outsider = await _setup(db)
                await update_project_config(
                    db,
                    project_id=PROJ,
                    user=owner,
                    custom_prompt="Secret project instructions.",
                    memory_enabled=True,
                )
                await create_project_memory(
                    db,
                    project_id=PROJ,
                    user=owner,
                    content="Internal launch date is March.",
                )
                project_session = await _chat(
                    db, owner, project_id=PROJ, sid="owner-proj"
                )
                personal = await _chat(
                    db, outsider, project_id=None, sid="outsider-personal"
                )

                spoofed = await plan_project_turn(
                    db,
                    _user_messages("hello"),
                    user_id=outsider.id,
                    chat_session_id=personal.id,
                    client_project_id=PROJ,
                )
                leaked = await plan_project_turn(
                    db,
                    _user_messages("hello"),
                    user_id=outsider.id,
                    chat_session_id=project_session.id,
                    client_project_id=PROJ,
                )
                for out in (spoofed, leaked):
                    blob = _joined(out)
                    assert "Secret project instructions" not in blob
                    assert "Project instructions" not in blob
                    assert "Internal launch date" not in blob
        finally:
            await engine.dispose()

    asyncio.run(run())
