"""Structured Knowledge citations and deterministic reference verification."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

_CITATION_RE = re.compile(r"\[\[cite:([A-Za-z0-9._:-]{1,128})\]\]")


@dataclass(frozen=True)
class KnowledgeCitation:
    citation_id: str
    chunk_id: str
    document_id: str
    document_version_id: str
    knowledge_base_id: str
    release_id: str
    title: str
    file_name: str
    mime_type: str
    page_number: int | None
    section: str | None
    authority: str
    classification: str
    effective_from: str | None
    effective_to: str | None
    content_hash: str

    @property
    def marker(self) -> str:
        return f"[[cite:{self.citation_id}]]"

    def as_dict(self) -> dict:
        return {**asdict(self), "marker": self.marker}


@dataclass(frozen=True)
class CitationVerification:
    valid: bool
    cited_ids: tuple[str, ...]
    unknown_ids: tuple[str, ...]
    missing_required: bool
    malformed: bool


def extract_citation_ids(answer: str) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in _CITATION_RE.findall(answer or ""):
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def verify_answer_citations(
    answer: str,
    citations: Sequence[KnowledgeCitation],
    *,
    citations_required: bool,
) -> CitationVerification:
    cited_ids = extract_citation_ids(answer)
    available = {citation.citation_id for citation in citations}
    unknown = tuple(value for value in cited_ids if value not in available)
    missing_required = bool(citations_required and available and not cited_ids)
    # Any citation opener that was not consumed by the strict grammar is
    # malformed and must never be turned into a clickable source.
    malformed = (answer or "").count("[[cite:") != len(
        _CITATION_RE.findall(answer or "")
    )
    return CitationVerification(
        valid=not unknown and not missing_required and not malformed,
        cited_ids=cited_ids,
        unknown_ids=unknown,
        missing_required=missing_required,
        malformed=malformed,
    )


def citation_instruction(citations: Sequence[KnowledgeCitation]) -> str:
    if not citations:
        return ""
    markers = ", ".join(citation.marker for citation in citations)
    return (
        "Cite factual claims only with the exact source markers supplied in the "
        f"evidence. Available markers: {markers}. Never invent a marker."
    )
