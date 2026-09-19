"""An approval that set the two-person rule aside says so.

A Super Admin may complete both the maker and the checker step
(``user_bypasses_maker_checker``) - that is the deliberate break-glass. But the
audit row it produced was byte-identical to a properly two-person approval, so
nothing downstream could tell them apart.

For a separation-of-duties control, "the control was bypassed" is the one fact
the trail has to carry. Without it the control is only as good as the assumption
that nobody used the escape hatch.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models.knowledge import (
    KnowledgeAuditEvent,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.services.knowledge_ingestion_service import approve_document_version


async def _version_in_review(db_session, *, uploader_id: int, suffix: str) -> KnowledgeDocumentVersion:
    base = KnowledgeBase(id=f"kb-break-{suffix}", name="Handbook", slug=f"handbook-{suffix}")
    db_session.add(base)
    document = KnowledgeDocument(
        id=f"doc-break-{suffix}",
        knowledge_base_id=base.id,
        canonical_key=f"policy-{suffix}.pdf",
        title="Policy",
        status="draft",
    )
    db_session.add(document)
    version = KnowledgeDocumentVersion(
        id=f"ver-break-{suffix}",
        document_id=document.id,
        version_number=1,
        status="review",
        storage_key=f"kb/{suffix}/v1",
        file_name="policy.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        sha256="d" * 64,
        uploaded_by_user_id=uploader_id,
    )
    db_session.add(version)
    await db_session.flush()
    return version


async def _approval_label(db_session, version) -> str:
    row = (
        (
            await db_session.execute(
                select(KnowledgeAuditEvent).where(
                    KnowledgeAuditEvent.event_type == "document.version.approved",
                    KnowledgeAuditEvent.document_id == version.document_id,
                )
            )
        )
        .scalars()
        .one()
    )
    payload = row.payload_json if isinstance(row.payload_json, dict) else json.loads(row.payload_json)
    return payload["maker_checker"]


async def test_a_two_person_approval_is_labelled_as_one(db_session, user, admin):
    version = await _version_in_review(db_session, uploader_id=user.id, suffix="two")

    await approve_document_version(
        db_session,
        document_version_id=version.id,
        reviewer_user_id=admin.id,
        reason="Checked by a second pair of eyes",
    )
    await db_session.flush()

    assert await _approval_label(db_session, version) == "two_person"
    assert version.metadata_json["approval"]["maker_checker"] == "two_person"


async def test_a_self_approval_is_labelled_break_glass(db_session, user):
    version = await _version_in_review(db_session, uploader_id=user.id, suffix="glass")

    await approve_document_version(
        db_session,
        document_version_id=version.id,
        reviewer_user_id=user.id,
        reason="Break-glass: no second reviewer available",
        allow_self_review=True,
    )
    await db_session.flush()

    assert await _approval_label(db_session, version) == "break_glass", (
        "a self-approval is indistinguishable from a properly reviewed one"
    )
    assert version.metadata_json["approval"]["maker_checker"] == "break_glass"


def test_the_publish_payload_distinguishes_the_two(monkeypatch):
    """Read the branch directly: the full publish path needs a policy-valid version."""

    import inspect

    from app.services import agent_definition_service

    source = inspect.getsource(agent_definition_service.publish_agent_version)
    assert '"maker_checker": "break_glass" if break_glass else "two_person"' in source
    assert "break_glass = bool(allow_same_actor and self_publish)" in source


def test_a_knowledge_approval_records_which_it_was():
    import inspect

    from app.services import knowledge_ingestion_service

    source = inspect.getsource(knowledge_ingestion_service.approve_document_version)
    assert source.count('"maker_checker": "break_glass" if break_glass else "two_person"') == 2, (
        "both the stored approval and the audit event must say which it was"
    )
    assert "break_glass = bool(allow_self_review and self_review)" in source


@pytest.mark.parametrize(
    ("allow", "same_actor", "expected"),
    [
        (False, False, "two_person"),
        (True, False, "two_person"),
        (True, True, "break_glass"),
    ],
)
def test_the_label_only_says_break_glass_when_it_was_used(allow, same_actor, expected):
    """Holding the bypass permission is not the same as having used it."""

    break_glass = bool(allow and same_actor)
    assert ("break_glass" if break_glass else "two_person") == expected


def test_the_maker_is_named_alongside_the_label():
    """Whose separation was set aside is part of the answer."""

    import inspect

    from app.services import agent_definition_service, knowledge_ingestion_service

    assert '"created_by_user_id": version.created_by_user_id,' in inspect.getsource(
        agent_definition_service.publish_agent_version
    )
    assert '"uploaded_by_user_id": version.uploaded_by_user_id,' in inspect.getsource(
        knowledge_ingestion_service.approve_document_version
    )
