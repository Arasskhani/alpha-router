"""ACL-safe hybrid retrieval, RRF fusion, reranking, and context packing."""

from __future__ import annotations

import datetime
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent import AgentKnowledgeBinding, AgentVersion
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
    KnowledgeRelease,
    KnowledgeReleaseDocument,
)
from app.services.knowledge_citation_service import KnowledgeCitation
from app.services.knowledge_crypto_service import (
    chunk_plaintext_hash,
    decrypt_text,
)
from app.services.knowledge_embedding_service import KnowledgeEmbeddingBackend
from app.services.knowledge_rerank_service import (
    DeterministicKnowledgeReranker,
    KnowledgeReranker,
    RerankCandidate,
)
from app.services.knowledge_sparse_service import (
    SparseEncodingProfile,
    encode_sparse_query,
)
from app.services.qdrant_service import (
    KnowledgeSearchHit,
    QdrantVectorService,
)
from app.services.resource_access_service import (
    ResourceAccessSubject,
    filter_documents_for_subject,
    filter_knowledge_bases_for_subject,
)

_MAX_KNOWLEDGE_BASES_PER_AGENT = 64
_MAX_CANDIDATES = 1_000
_MAX_FINAL_RESULTS = 32
_MAX_CONTEXT_TOKENS = 32_768


class KnowledgeRetrievalUnavailable(RuntimeError):
    """Raised when fail-closed retrieval cannot reach a required component."""


@dataclass(frozen=True)
class RetrievalPolicy:
    candidate_limit: int
    final_limit: int
    rrf_k: int
    max_chunks_per_document: int
    context_token_budget: int
    minimum_answerability_score: float
    dense_weight: float
    sparse_weight: float
    dense_score_threshold: float
    sparse_score_threshold: float
    citations_required: bool
    fail_closed: bool

    @classmethod
    def from_dict(cls, raw: dict | None) -> RetrievalPolicy:
        settings = get_settings()
        value = dict(raw or {})

        def bounded_int(key: str, default: int, *, minimum: int, maximum: int) -> int:
            return max(minimum, min(maximum, int(value.get(key, default))))

        def bounded_float(
            key: str,
            default: float,
            *,
            minimum: float,
            maximum: float,
        ) -> float:
            return max(minimum, min(maximum, float(value.get(key, default))))

        return cls(
            candidate_limit=bounded_int(
                "candidate_limit",
                settings.knowledge_retrieval_candidate_limit,
                minimum=1,
                maximum=200,
            ),
            final_limit=bounded_int(
                "final_limit",
                settings.knowledge_retrieval_final_limit,
                minimum=1,
                maximum=_MAX_FINAL_RESULTS,
            ),
            rrf_k=bounded_int(
                "rrf_k",
                settings.knowledge_retrieval_rrf_k,
                minimum=1,
                maximum=1_000,
            ),
            max_chunks_per_document=bounded_int(
                "max_chunks_per_document",
                settings.knowledge_retrieval_max_chunks_per_document,
                minimum=1,
                maximum=10,
            ),
            context_token_budget=bounded_int(
                "context_token_budget",
                settings.knowledge_retrieval_context_token_budget,
                minimum=128,
                maximum=_MAX_CONTEXT_TOKENS,
            ),
            minimum_answerability_score=bounded_float(
                "minimum_answerability_score",
                0.35,
                minimum=0.0,
                maximum=1.0,
            ),
            dense_weight=bounded_float(
                "dense_weight",
                1.0,
                minimum=0.0,
                maximum=10.0,
            ),
            sparse_weight=bounded_float(
                "sparse_weight",
                1.0,
                minimum=0.0,
                maximum=10.0,
            ),
            dense_score_threshold=bounded_float(
                "dense_score_threshold",
                settings.knowledge_retrieval_dense_score_threshold,
                minimum=-1.0,
                maximum=1.0,
            ),
            sparse_score_threshold=bounded_float(
                "sparse_score_threshold",
                settings.knowledge_retrieval_sparse_score_threshold,
                minimum=0.0,
                maximum=1_000_000.0,
            ),
            citations_required=bool(value.get("citations_required", True)),
            fail_closed=bool(value.get("fail_closed", True)),
        )


@dataclass(frozen=True)
class FusedCandidate:
    chunk_id: str
    release_id: str
    index_version_id: str
    payload: dict[str, Any]
    rrf_score: float
    dense_score: float | None
    sparse_score: float | None
    dense_rank: int | None
    sparse_rank: int | None


@dataclass(frozen=True)
class RetrievedEvidence:
    rank: int
    text: str
    child_text: str
    rerank_score: float
    rrf_score: float
    dense_score: float | None
    sparse_score: float | None
    citation: KnowledgeCitation


@dataclass(frozen=True)
class KnowledgeContextPack:
    text: str
    citations: tuple[KnowledgeCitation, ...]
    estimated_tokens: int
    truncated: bool


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    evidence: tuple[RetrievedEvidence, ...]
    context: KnowledgeContextPack
    answerable: bool
    abstention_reason: str | None
    knowledge_release_ids: tuple[str, ...]
    index_version_ids: tuple[str, ...]
    candidate_count: int
    post_authorized_count: int
    component_errors: tuple[str, ...]


@dataclass(frozen=True)
class _RetrievalSource:
    knowledge_base: KnowledgeBase
    release: KnowledgeRelease
    index_version: KnowledgeIndexVersion


@dataclass(frozen=True)
class _AuthorizedCandidate:
    fused: FusedCandidate
    chunk: KnowledgeChunk
    context_chunk: KnowledgeChunk
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    child_text: str
    context_text: str


def _match_value(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _acl_layer_filter(
    *,
    scope_field: str,
    unrestricted_value: str,
    allow_field: str,
    principal_tokens: Sequence[str],
) -> models.Filter:
    conditions: list[models.FieldCondition] = [_match_value(scope_field, unrestricted_value)]
    if principal_tokens:
        conditions.append(
            models.FieldCondition(
                key=allow_field,
                match=models.MatchAny(any=list(principal_tokens)),
            )
        )
    return models.Filter(should=conditions)


def build_qdrant_retrieval_filter(
    *,
    release_id: str,
    subject: ResourceAccessSubject,
    now: datetime.datetime,
) -> models.Filter:
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.UTC)
    must: list = [
        _match_value("release_id", release_id),
        _match_value("status", "active"),
        models.Filter(
            should=[
                models.IsEmptyCondition(is_empty=models.PayloadField(key="effective_from")),
                models.FieldCondition(
                    key="effective_from",
                    range=models.DatetimeRange(lte=now),
                ),
            ]
        ),
        models.Filter(
            should=[
                models.IsEmptyCondition(is_empty=models.PayloadField(key="effective_to")),
                models.FieldCondition(
                    key="effective_to",
                    range=models.DatetimeRange(gte=now),
                ),
            ]
        ),
        models.IsEmptyCondition(is_empty=models.PayloadField(key="revoked_at")),
    ]
    must_not: list = []
    if not subject.break_glass:
        tokens = sorted(subject.principal_tokens)
        must.extend(
            [
                _acl_layer_filter(
                    scope_field="kb_access_scope",
                    unrestricted_value="public",
                    allow_field="kb_allow_principal_tokens",
                    principal_tokens=tokens,
                ),
                _acl_layer_filter(
                    scope_field="document_access_scope",
                    unrestricted_value="inherited",
                    allow_field="document_allow_principal_tokens",
                    principal_tokens=tokens,
                ),
            ]
        )
        if tokens:
            must_not.append(
                models.FieldCondition(
                    key="deny_principal_tokens",
                    match=models.MatchAny(any=tokens),
                )
            )
    return models.Filter(must=must, must_not=must_not or None)


def reciprocal_rank_fusion(
    rankings: Sequence[tuple[str, Sequence[KnowledgeSearchHit], float]],
    *,
    release_id: str,
    index_version_id: str,
    rrf_k: int,
) -> list[FusedCandidate]:
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    accumulated: dict[str, dict[str, Any]] = {}
    for channel, hits, weight in rankings:
        if weight <= 0:
            continue
        for rank, hit in enumerate(hits, start=1):
            chunk_id = str(hit.payload.get("chunk_id") or hit.point_id)
            if not chunk_id or chunk_id != str(hit.point_id):
                continue
            item = accumulated.setdefault(
                chunk_id,
                {
                    "payload": dict(hit.payload),
                    "rrf_score": 0.0,
                    "dense_score": None,
                    "sparse_score": None,
                    "dense_rank": None,
                    "sparse_rank": None,
                },
            )
            item["rrf_score"] += float(weight) / float(rrf_k + rank)
            item[f"{channel}_score"] = float(hit.score)
            item[f"{channel}_rank"] = rank
    fused = [
        FusedCandidate(
            chunk_id=chunk_id,
            release_id=release_id,
            index_version_id=index_version_id,
            payload=item["payload"],
            rrf_score=float(item["rrf_score"]),
            dense_score=item["dense_score"],
            sparse_score=item["sparse_score"],
            dense_rank=item["dense_rank"],
            sparse_rank=item["sparse_rank"],
        )
        for chunk_id, item in accumulated.items()
    ]
    fused.sort(key=lambda item: (-item.rrf_score, item.chunk_id))
    return fused


async def _resolve_sources(
    db: AsyncSession,
    *,
    agent_version: AgentVersion,
    subject: ResourceAccessSubject,
) -> list[_RetrievalSource]:
    bindings = (
        (
            await db.execute(
                select(AgentKnowledgeBinding)
                .where(
                    AgentKnowledgeBinding.agent_version_id == agent_version.id,
                    AgentKnowledgeBinding.status == "published",
                )
                .order_by(AgentKnowledgeBinding.knowledge_base_id)
                .limit(_MAX_KNOWLEDGE_BASES_PER_AGENT + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(bindings) > _MAX_KNOWLEDGE_BASES_PER_AGENT:
        raise ValueError("Agent Knowledge bindings exceed the runtime safety limit")
    knowledge_base_ids = sorted({binding.knowledge_base_id for binding in bindings})
    if not knowledge_base_ids:
        return []
    knowledge_bases = (
        (
            await db.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(knowledge_base_ids),
                    KnowledgeBase.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    allowed = {
        knowledge_base.id: knowledge_base
        for knowledge_base in await filter_knowledge_bases_for_subject(
            db,
            knowledge_bases,
            subject,
        )
    }
    sources: list[_RetrievalSource] = []
    for binding in bindings:
        knowledge_base = allowed.get(binding.knowledge_base_id)
        if knowledge_base is None:
            continue
        if binding.release_mode == "pinned":
            release = await db.get(KnowledgeRelease, binding.pinned_release_id) if binding.pinned_release_id else None
            if (
                release is None
                or release.knowledge_base_id != knowledge_base.id
                or release.status not in {"published", "archived"}
            ):
                continue
        else:
            release = (
                await db.execute(
                    select(KnowledgeRelease).where(
                        KnowledgeRelease.knowledge_base_id == knowledge_base.id,
                        KnowledgeRelease.active_scope_key == f"kb-release:{knowledge_base.id}",
                        KnowledgeRelease.status == "published",
                    )
                )
            ).scalar_one_or_none()
            if release is None:
                continue
        index_version = (
            (
                await db.execute(
                    select(KnowledgeIndexVersion)
                    .where(
                        KnowledgeIndexVersion.release_id == release.id,
                        KnowledgeIndexVersion.status.in_(["active", "retired"]),
                    )
                    .order_by(KnowledgeIndexVersion.version_number.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if index_version is not None:
            sources.append(
                _RetrievalSource(
                    knowledge_base=knowledge_base,
                    release=release,
                    index_version=index_version,
                )
            )
    return sources


def _temporally_valid(
    version: KnowledgeDocumentVersion,
    *,
    now: datetime.datetime,
) -> bool:
    comparable_now = now.replace(tzinfo=None) if now.tzinfo is not None else now
    if version.effective_from and version.effective_from > comparable_now:
        return False
    if version.effective_to and version.effective_to < comparable_now:
        return False
    return version.revoked_at is None


async def _post_authorize_candidates(
    db: AsyncSession,
    *,
    candidates: Sequence[FusedCandidate],
    subject: ResourceAccessSubject,
    now: datetime.datetime,
) -> list[_AuthorizedCandidate]:
    bounded = list(candidates[:_MAX_CANDIDATES])
    if not bounded:
        return []
    chunk_ids = [candidate.chunk_id for candidate in bounded]
    rows = (
        await db.execute(
            select(KnowledgeChunk, KnowledgeDocumentVersion, KnowledgeDocument)
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeChunk.document_version_id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
            )
            .where(KnowledgeChunk.id.in_(chunk_ids))
        )
    ).all()
    row_by_chunk = {str(chunk.id): (chunk, version, document) for chunk, version, document in rows}
    documents = list({document.id: document for _, _, document in rows}.values())
    allowed_document_ids = {document.id for document in await filter_documents_for_subject(db, documents, subject)}
    release_ids = sorted({candidate.release_id for candidate in bounded})
    memberships = {
        (str(release_id), str(document_version_id))
        for release_id, document_version_id in (
            await db.execute(
                select(
                    KnowledgeReleaseDocument.release_id,
                    KnowledgeReleaseDocument.document_version_id,
                ).where(KnowledgeReleaseDocument.release_id.in_(release_ids))
            )
        ).all()
    }
    releases = {
        release.id: release
        for release in (
            (await db.execute(select(KnowledgeRelease).where(KnowledgeRelease.id.in_(release_ids)))).scalars().all()
        )
    }

    prelim: list[
        tuple[
            FusedCandidate,
            KnowledgeChunk,
            KnowledgeDocumentVersion,
            KnowledgeDocument,
        ]
    ] = []
    parent_ids: set[str] = set()
    for candidate in bounded:
        row = row_by_chunk.get(candidate.chunk_id)
        release = releases.get(candidate.release_id)
        if (
            row is None
            or release is None
            or release.status
            not in {
                "published",
                "archived",
            }
        ):
            continue
        chunk, version, document = row
        payload = candidate.payload
        if (
            document.id not in allowed_document_ids
            or document.status != "active"
            or document.revoked_at is not None
            or document.deleted_at is not None
            or version.status not in {"published", "superseded"}
            or not _temporally_valid(version, now=now)
            or (candidate.release_id, version.id) not in memberships
            or str(payload.get("document_id") or "") != document.id
            or str(payload.get("document_version_id") or "") != version.id
            or str(payload.get("knowledge_base_id") or "") != document.knowledge_base_id
            or str(payload.get("release_id") or "") != candidate.release_id
            or str(payload.get("index_version_id") or "") != candidate.index_version_id
            or str(payload.get("content_hash") or "") != chunk.content_hash
        ):
            continue
        prelim.append((candidate, chunk, version, document))
        if chunk.parent_chunk_id:
            parent_ids.add(str(chunk.parent_chunk_id))

    parents = {
        chunk.id: chunk
        for chunk in (
            (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(parent_ids)))).scalars().all()
            if parent_ids
            else []
        )
    }
    authorized: list[_AuthorizedCandidate] = []
    for candidate, chunk, version, document in prelim:
        child_text = decrypt_text(
            chunk.content,
            associated_data=f"knowledge-chunk:{chunk.id}",
        )
        if chunk_plaintext_hash(int(chunk.chunk_index), child_text) != chunk.content_hash:
            raise ValueError("Knowledge child chunk integrity verification failed")
        context_chunk = parents.get(chunk.parent_chunk_id) or chunk
        if context_chunk.document_version_id != chunk.document_version_id:
            continue
        if context_chunk.id == chunk.id:
            context_text = child_text
        else:
            context_text = decrypt_text(
                context_chunk.content,
                associated_data=f"knowledge-chunk:{context_chunk.id}",
            )
            if chunk_plaintext_hash(int(context_chunk.chunk_index), context_text) != context_chunk.content_hash:
                raise ValueError("Knowledge parent chunk integrity verification failed")
        authorized.append(
            _AuthorizedCandidate(
                fused=candidate,
                chunk=chunk,
                context_chunk=context_chunk,
                document=document,
                version=version,
                child_text=child_text,
                context_text=context_text,
            )
        )
    return authorized


def _citation_for(candidate: _AuthorizedCandidate) -> KnowledgeCitation:
    version = candidate.version
    chunk = candidate.chunk
    return KnowledgeCitation(
        citation_id=str(chunk.id),
        chunk_id=str(chunk.id),
        document_id=str(candidate.document.id),
        document_version_id=str(version.id),
        knowledge_base_id=str(candidate.document.knowledge_base_id),
        release_id=candidate.fused.release_id,
        title=candidate.document.title,
        file_name=version.file_name,
        mime_type=version.mime_type,
        page_number=chunk.page_number,
        section=chunk.section,
        authority=version.authority,
        classification=version.classification,
        effective_from=(version.effective_from.isoformat() if version.effective_from else None),
        effective_to=version.effective_to.isoformat() if version.effective_to else None,
        content_hash=chunk.content_hash,
    )


def _pack_context(
    evidence: Sequence[RetrievedEvidence],
    *,
    token_budget: int,
) -> KnowledgeContextPack:
    blocks: list[str] = []
    citations: list[KnowledgeCitation] = []
    used_tokens = 0
    truncated = False
    for item in evidence:
        overhead = 80
        # One UTF-8 byte per token is a deliberately conservative upper bound
        # when the eventual generation model/tokenizer is not yet known.
        estimated = max(1, len(item.text.encode("utf-8"))) + overhead
        text = item.text
        remaining = token_budget - used_tokens - overhead
        if remaining <= 0:
            truncated = True
            break
        if estimated > token_budget - used_tokens:
            if blocks:
                truncated = True
                break
            encoded = text.encode("utf-8")[: max(1, remaining)]
            text = encoded.decode("utf-8", errors="ignore")
            estimated = max(1, len(text.encode("utf-8"))) + overhead
            truncated = True
        payload = {
            "citation_id": item.citation.citation_id,
            "title": item.citation.title,
            "section": item.citation.section,
            "page_number": item.citation.page_number,
            "authority": item.citation.authority,
            "effective_from": item.citation.effective_from,
            "effective_to": item.citation.effective_to,
            "content": text,
        }
        blocks.append(
            "BEGIN_UNTRUSTED_KNOWLEDGE_EVIDENCE\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\nEND_UNTRUSTED_KNOWLEDGE_EVIDENCE"
        )
        citations.append(item.citation)
        used_tokens += estimated
    return KnowledgeContextPack(
        text="\n\n".join(blocks),
        citations=tuple(citations),
        estimated_tokens=used_tokens,
        truncated=truncated,
    )


async def retrieve_knowledge(
    db: AsyncSession,
    *,
    agent_version_id: str,
    subject: ResourceAccessSubject,
    query: str,
    qdrant: QdrantVectorService,
    embedding_backend: KnowledgeEmbeddingBackend,
    reranker: KnowledgeReranker | None = None,
    now: datetime.datetime | None = None,
) -> KnowledgeRetrievalResult:
    clean_query = " ".join((query or "").split())
    settings = get_settings()
    if not clean_query:
        raise ValueError("Knowledge retrieval query cannot be empty")
    if len(clean_query) > settings.knowledge_retrieval_max_query_characters:
        raise ValueError("Knowledge retrieval query exceeds the configured limit")
    if not subject.active:
        return KnowledgeRetrievalResult(
            evidence=(),
            context=KnowledgeContextPack("", (), 0, False),
            answerable=False,
            abstention_reason="inactive_subject",
            knowledge_release_ids=(),
            index_version_ids=(),
            candidate_count=0,
            post_authorized_count=0,
            component_errors=(),
        )
    agent_version = await db.get(AgentVersion, agent_version_id)
    if (
        agent_version is None
        or agent_version.status not in {"published", "archived"}
        or (agent_version.status == "archived" and agent_version.published_at is None)
    ):
        raise ValueError("A previously published Agent version is required for Knowledge retrieval")
    policy = RetrievalPolicy.from_dict(agent_version.retrieval_policy)
    current_time = now or datetime.datetime.now(datetime.UTC)
    sources = await _resolve_sources(
        db,
        agent_version=agent_version,
        subject=subject,
    )
    if not sources:
        return KnowledgeRetrievalResult(
            evidence=(),
            context=KnowledgeContextPack("", (), 0, False),
            answerable=False,
            abstention_reason="no_accessible_knowledge",
            knowledge_release_ids=(),
            index_version_ids=(),
            candidate_count=0,
            post_authorized_count=0,
            component_errors=(),
        )

    vectors_by_profile: dict[tuple[str, str, int, str], list[float]] = {}
    all_fused: list[FusedCandidate] = []
    component_errors: list[str] = []
    for source in sources:
        index_version = source.index_version
        profile_key = (
            index_version.embedding_provider,
            index_version.embedding_model,
            int(index_version.embedding_dimensions),
            index_version.embedding_fingerprint,
        )
        try:
            dense = vectors_by_profile.get(profile_key)
            if dense is None:
                dense = (
                    await embedding_backend.embed(
                        db,
                        provider=index_version.embedding_provider,
                        model=index_version.embedding_model,
                        dimensions=index_version.embedding_dimensions,
                        texts=[clean_query],
                    )
                )[0]
                vectors_by_profile[profile_key] = dense
            sparse_profile = SparseEncodingProfile.from_dict(index_version.sparse_profile)
            dense_hits, sparse_hits = await qdrant.hybrid_candidates(
                collection_name=index_version.collection_name,
                dense=dense,
                sparse=encode_sparse_query(
                    clean_query,
                    profile=sparse_profile,
                ),
                query_filter=build_qdrant_retrieval_filter(
                    release_id=source.release.id,
                    subject=subject,
                    now=current_time,
                ),
                limit=policy.candidate_limit,
                dense_score_threshold=policy.dense_score_threshold,
                sparse_score_threshold=policy.sparse_score_threshold,
            )
            all_fused.extend(
                reciprocal_rank_fusion(
                    [
                        ("dense", dense_hits, policy.dense_weight),
                        ("sparse", sparse_hits, policy.sparse_weight),
                    ],
                    release_id=source.release.id,
                    index_version_id=index_version.id,
                    rrf_k=policy.rrf_k,
                )
            )
        except Exception as exc:
            if policy.fail_closed:
                raise KnowledgeRetrievalUnavailable(
                    f"Knowledge retrieval failed for {source.knowledge_base.id}"
                ) from exc
            component_errors.append(f"{source.knowledge_base.id}:{type(exc).__name__}")

    all_fused.sort(key=lambda item: (-item.rrf_score, item.chunk_id))
    all_fused = all_fused[:_MAX_CANDIDATES]
    authorized = await _post_authorize_candidates(
        db,
        candidates=all_fused,
        subject=subject,
        now=current_time,
    )
    if not authorized:
        return KnowledgeRetrievalResult(
            evidence=(),
            context=KnowledgeContextPack("", (), 0, False),
            answerable=False,
            abstention_reason="no_authorized_evidence",
            knowledge_release_ids=tuple(sorted({source.release.id for source in sources})),
            index_version_ids=tuple(sorted({source.index_version.id for source in sources})),
            candidate_count=len(all_fused),
            post_authorized_count=0,
            component_errors=tuple(component_errors),
        )

    authorized_by_key = {candidate.fused.chunk_id: candidate for candidate in authorized}
    reranked = await (reranker or DeterministicKnowledgeReranker()).rerank(
        query=clean_query,
        candidates=[
            RerankCandidate(
                key=candidate.fused.chunk_id,
                text=candidate.child_text,
                rrf_score=candidate.fused.rrf_score,
                authority=candidate.version.authority,
                effective_from=candidate.version.effective_from,
            )
            for candidate in authorized
        ],
        limit=min(len(authorized), _MAX_CANDIDATES),
    )
    selected: list[RetrievedEvidence] = []
    per_document: defaultdict[str, int] = defaultdict(int)
    used_context_chunks: set[str] = set()
    for reranked_item in reranked:
        candidate = authorized_by_key.get(reranked_item.candidate.key)
        if candidate is None:
            continue
        document_id = str(candidate.document.id)
        context_chunk_id = str(candidate.context_chunk.id)
        if per_document[document_id] >= policy.max_chunks_per_document or context_chunk_id in used_context_chunks:
            continue
        per_document[document_id] += 1
        used_context_chunks.add(context_chunk_id)
        selected.append(
            RetrievedEvidence(
                rank=len(selected) + 1,
                text=candidate.context_text,
                child_text=candidate.child_text,
                rerank_score=reranked_item.score,
                rrf_score=candidate.fused.rrf_score,
                dense_score=candidate.fused.dense_score,
                sparse_score=candidate.fused.sparse_score,
                citation=_citation_for(candidate),
            )
        )
        if len(selected) >= policy.final_limit:
            break

    context = _pack_context(
        selected,
        token_budget=policy.context_token_budget,
    )
    included_ids = {citation.citation_id for citation in context.citations}
    selected = [evidence for evidence in selected if evidence.citation.citation_id in included_ids]
    top_score = selected[0].rerank_score if selected else 0.0
    answerable = bool(selected) and top_score >= policy.minimum_answerability_score
    return KnowledgeRetrievalResult(
        evidence=tuple(selected),
        context=context,
        answerable=answerable,
        abstention_reason=None if answerable else "insufficient_evidence",
        knowledge_release_ids=tuple(sorted({evidence.citation.release_id for evidence in selected})),
        index_version_ids=tuple(
            sorted({authorized_by_key[evidence.citation.chunk_id].fused.index_version_id for evidence in selected})
        ),
        candidate_count=len(all_fused),
        post_authorized_count=len(authorized),
        component_errors=tuple(component_errors),
    )
