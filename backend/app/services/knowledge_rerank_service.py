"""Bounded, deterministic reranking for post-authorized Knowledge evidence."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.services.knowledge_sparse_service import lexical_tokens


@dataclass(frozen=True)
class RerankCandidate:
    key: str
    text: str
    rrf_score: float
    authority: str
    effective_from: datetime.datetime | None = None


@dataclass(frozen=True)
class RerankedCandidate:
    candidate: RerankCandidate
    score: float
    lexical_score: float
    authority_score: float


class KnowledgeReranker(Protocol):
    async def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[RerankCandidate],
        limit: int,
    ) -> list[RerankedCandidate]: ...


def _authority_score(authority: str) -> float:
    normalized = (authority or "").strip().casefold()
    if normalized in {"canonical", "authoritative", "official", "policy"}:
        return 1.0
    if normalized in {"reference", "approved"}:
        return 0.65
    if normalized in {"informational", "community"}:
        return 0.35
    return 0.5


def _lexical_score(query: str, text: str) -> float:
    query_tokens = lexical_tokens(query)
    if not query_tokens:
        return 0.0
    query_set = set(query_tokens)
    text_set = set(lexical_tokens(text))
    if not text_set:
        return 0.0
    coverage = len(query_set & text_set) / len(query_set)
    normalized_query = " ".join(query_tokens)
    normalized_text = " ".join(lexical_tokens(text))
    phrase_bonus = (
        0.15 if normalized_query and normalized_query in normalized_text else 0.0
    )
    return min(1.0, coverage + phrase_bonus)


class DeterministicKnowledgeReranker:
    """Stable fallback until a corpus-benchmarked cross-encoder is configured."""

    async def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[RerankCandidate],
        limit: int,
    ) -> list[RerankedCandidate]:
        if limit < 1:
            return []
        bounded = list(candidates[:1_000])
        max_rrf = max((candidate.rrf_score for candidate in bounded), default=0.0)
        results: list[RerankedCandidate] = []
        for candidate in bounded:
            lexical = _lexical_score(query, candidate.text)
            authority = _authority_score(candidate.authority)
            normalized_rrf = candidate.rrf_score / max_rrf if max_rrf > 0 else 0.0
            # Dense+sparse RRF remains the dominant signal. Lexical coverage
            # and source authority provide transparent tie-breaking.
            score = (0.65 * normalized_rrf) + (0.25 * lexical) + (0.10 * authority)
            results.append(
                RerankedCandidate(
                    candidate=candidate,
                    score=score,
                    lexical_score=lexical,
                    authority_score=authority,
                )
            )
        results.sort(key=lambda item: (-item.score, item.candidate.key))
        return results[:limit]
