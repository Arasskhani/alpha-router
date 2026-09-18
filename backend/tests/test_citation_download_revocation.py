"""Revoking a document has to stop its citation downloads.

``GET /api/agents/citations/{run}/{citation}/content`` returns the entire
original file, checking only that the agent run belongs to the caller. Retrieval
itself only ever exposed excerpts, so this endpoint escalates a citation into
the whole document - and it did so permanently: revoking a version, revoking the
document or deleting it left every past run's download link working.

Revocation has to be evaluated when the file is handed over, not when the turn
happened.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi import HTTPException

from app.api.agents import download_citation_source
from app.models.agent_runtime import AgentCitation, AgentRun
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)


async def _cited_document(db_session, user) -> tuple[str, str]:
    base = KnowledgeBase(id="kb-1", name="Handbook", slug="handbook")
    db_session.add(base)
    document = KnowledgeDocument(id="doc-1", knowledge_base_id=base.id, canonical_key="policy.pdf", title="Policy")
    db_session.add(document)
    version = KnowledgeDocumentVersion(
        id="ver-1",
        document_id=document.id,
        version_number=1,
        storage_key="kb/doc-1/v1",
        file_name="policy.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        sha256="b" * 64,
    )
    db_session.add(version)
    run = AgentRun(
        id="run-1",
        correlation_id="corr-1",
        user_id=user.id,
        source="chat",
        status="succeeded",
        routing_outcome="explicit",
        query_sha256="a" * 64,
    )
    db_session.add(run)
    await db_session.flush()
    citation = AgentCitation(
        id="cit-1",
        agent_run_id=run.id,
        citation_id="c1",
        knowledge_base_id=base.id,
        document_id=document.id,
        document_version_id=version.id,
        title="Policy",
        file_name="policy.pdf",
        mime_type="application/pdf",
        authority="reference",
        classification="internal",
        content_hash="c" * 64,
    )
    db_session.add(citation)
    await db_session.flush()
    return run.id, citation.citation_id


@pytest.mark.parametrize(
    "revoke",
    ["version_revoked", "document_revoked", "document_deleted"],
)
async def test_a_revoked_document_cannot_be_downloaded(db_session, user, revoke):
    run_id, citation_id = await _cited_document(db_session, user)
    now = datetime.datetime.utcnow()

    if revoke == "version_revoked":
        (await db_session.get(KnowledgeDocumentVersion, "ver-1")).revoked_at = now
    elif revoke == "document_revoked":
        (await db_session.get(KnowledgeDocument, "doc-1")).revoked_at = now
    else:
        (await db_session.get(KnowledgeDocument, "doc-1")).deleted_at = now
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await download_citation_source(run_id, citation_id, db_session, user)
    assert exc.value.status_code == 404
    assert "no longer available" in str(exc.value.detail)


async def test_a_live_document_still_reaches_the_object_store(db_session, user, monkeypatch):
    """The guard must reject for revocation, not for everything."""

    run_id, citation_id = await _cited_document(db_session, user)
    asked: list[str] = []

    class _Store:
        async def get(self, key, **_kwargs):
            asked.append(key)
            raise FileNotFoundError(key)

    monkeypatch.setattr("app.api.agents.default_knowledge_object_store", lambda: _Store())

    with pytest.raises(HTTPException) as exc:
        await download_citation_source(run_id, citation_id, db_session, user)

    assert asked == ["kb/doc-1/v1"], "a live citation must still be fetched"
    assert "no longer available" not in str(exc.value.detail)
