"""Deterministic multilingual sparse vectors for Qdrant hybrid retrieval."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.services.qdrant_service import SparseValues

SPARSE_ENCODER_VERSION = "hashed-lexical-idf-v1"
DEFAULT_HASH_SPACE = 2_147_483_647
DEFAULT_MAX_DOCUMENT_TERMS = 4_096
DEFAULT_MAX_QUERY_TERMS = 256

_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)
_ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_ARABIC_TO_PERSIAN = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
    }
)


@dataclass(frozen=True)
class SparseEncodingProfile:
    algorithm: str = SPARSE_ENCODER_VERSION
    hash_space: int = DEFAULT_HASH_SPACE
    max_document_terms: int = DEFAULT_MAX_DOCUMENT_TERMS
    max_query_terms: int = DEFAULT_MAX_QUERY_TERMS

    @classmethod
    def from_dict(cls, raw: dict | None) -> SparseEncodingProfile:
        value = dict(raw or {})
        algorithm = (
            str(value.get("algorithm") or SPARSE_ENCODER_VERSION).strip().lower()
        )
        # Older draft releases used the generic label "bm25". Qdrant applies
        # collection-level IDF; this encoder supplies deterministic hashed TF.
        if algorithm == "bm25":
            algorithm = SPARSE_ENCODER_VERSION
        if algorithm != SPARSE_ENCODER_VERSION:
            raise ValueError(f"Unsupported sparse encoding algorithm: {algorithm}")
        hash_space = int(value.get("hash_space") or DEFAULT_HASH_SPACE)
        max_document_terms = int(
            value.get("max_document_terms") or DEFAULT_MAX_DOCUMENT_TERMS
        )
        max_query_terms = int(value.get("max_query_terms") or DEFAULT_MAX_QUERY_TERMS)
        if hash_space < 65_536 or hash_space > DEFAULT_HASH_SPACE:
            raise ValueError("Sparse hash_space must be between 65536 and 2147483647")
        if max_document_terms < 1 or max_document_terms > 65_536:
            raise ValueError("Sparse max_document_terms is outside the safe range")
        if max_query_terms < 1 or max_query_terms > 4_096:
            raise ValueError("Sparse max_query_terms is outside the safe range")
        return cls(
            algorithm=algorithm,
            hash_space=hash_space,
            max_document_terms=max_document_terms,
            max_query_terms=max_query_terms,
        )

    def as_dict(self) -> dict[str, int | str]:
        return {
            "algorithm": self.algorithm,
            "hash_space": self.hash_space,
            "max_document_terms": self.max_document_terms,
            "max_query_terms": self.max_query_terms,
        }


def normalize_lexical_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = _ZERO_WIDTH_RE.sub(" ", normalized)
    normalized = normalized.translate(_ARABIC_TO_PERSIAN).casefold()
    return " ".join(normalized.split())


def lexical_tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(normalize_lexical_text(text)))


def _term_index(term: str, *, hash_space: int) -> int:
    digest = hashlib.blake2b(
        term.encode("utf-8"),
        digest_size=8,
        person=b"AR-SPARSE-V1",
    ).digest()
    return int.from_bytes(digest, "big") % hash_space


def _encode(
    text: str,
    *,
    profile: SparseEncodingProfile,
    max_terms: int,
) -> SparseValues:
    counts = Counter(lexical_tokens(text))
    if not counts:
        return SparseValues(indices=(), values=())

    # Keep the most informative bounded term set, with lexical ordering as a
    # deterministic tie-breaker. Hash collisions are merged before sorting.
    selected = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:max_terms]
    by_index: dict[int, float] = {}
    for term, frequency in selected:
        index = _term_index(term, hash_space=profile.hash_space)
        weight = 1.0 + math.log(float(frequency))
        by_index[index] = by_index.get(index, 0.0) + weight
    ordered = sorted(by_index.items())
    return SparseValues(
        indices=tuple(index for index, _ in ordered),
        values=tuple(value for _, value in ordered),
    )


def encode_sparse_document(
    text: str,
    *,
    profile: SparseEncodingProfile,
) -> SparseValues:
    return _encode(
        text,
        profile=profile,
        max_terms=profile.max_document_terms,
    )


def encode_sparse_query(
    text: str,
    *,
    profile: SparseEncodingProfile,
) -> SparseValues:
    return _encode(
        text,
        profile=profile,
        max_terms=profile.max_query_terms,
    )
