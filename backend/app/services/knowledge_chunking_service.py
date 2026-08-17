"""Deterministic parent/child chunking with citation-preserving metadata."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.services.knowledge_file_service import ParsedSegment

CHUNKER_VERSION = "hierarchical-char-v1"
DEFAULT_CHILD_CHARACTERS = 3_500
DEFAULT_CHILD_OVERLAP = 350
DEFAULT_PARENT_CHARACTERS = 12_000


@dataclass(frozen=True)
class ChunkDraft:
    local_key: str
    text: str
    page_number: int | None
    section: str | None
    parent_local_key: str | None
    kind: str


def _split_units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= DEFAULT_CHILD_CHARACTERS:
            units.append(paragraph)
            continue
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?؟])\s+", paragraph)
            if part.strip()
        ]
        units.extend(sentences or [paragraph])
    return units


def _window_text(
    text: str,
    *,
    target_characters: int,
    overlap_characters: int,
) -> list[str]:
    if len(text) <= target_characters:
        return [text]
    units = _split_units(text)
    windows: list[str] = []
    current: list[str] = []
    current_size = 0
    for unit in units:
        if len(unit) > target_characters:
            if current:
                windows.append("\n\n".join(current))
                current, current_size = [], 0
            start = 0
            while start < len(unit):
                end = min(len(unit), start + target_characters)
                windows.append(unit[start:end].strip())
                if end >= len(unit):
                    break
                start = max(start + 1, end - overlap_characters)
            continue
        addition = len(unit) + (2 if current else 0)
        if current and current_size + addition > target_characters:
            completed = "\n\n".join(current)
            windows.append(completed)
            overlap: list[str] = []
            overlap_size = 0
            for previous in reversed(current):
                if overlap_size + len(previous) > overlap_characters:
                    break
                overlap.insert(0, previous)
                overlap_size += len(previous) + 2
            current = overlap
            current_size = len("\n\n".join(current))
        current.append(unit)
        current_size += len(unit) + (2 if len(current) > 1 else 0)
    if current:
        windows.append("\n\n".join(current))
    return [window for window in windows if window]


def _key(prefix: str, segment_index: int, window_index: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{segment_index}:{window_index}:{digest}"


def chunk_segments(
    segments: tuple[ParsedSegment, ...],
    *,
    child_characters: int = DEFAULT_CHILD_CHARACTERS,
    overlap_characters: int = DEFAULT_CHILD_OVERLAP,
    parent_characters: int = DEFAULT_PARENT_CHARACTERS,
) -> tuple[ChunkDraft, ...]:
    if child_characters < 500:
        raise ValueError("child_characters must be at least 500")
    if overlap_characters < 0 or overlap_characters >= child_characters:
        raise ValueError("overlap_characters must be smaller than child_characters")
    if parent_characters < child_characters:
        raise ValueError("parent_characters must be at least child_characters")

    drafts: list[ChunkDraft] = []
    for segment_index, segment in enumerate(segments):
        parent_windows = _window_text(
            segment.text,
            target_characters=parent_characters,
            overlap_characters=0,
        )
        for parent_index, parent_text in enumerate(parent_windows):
            child_windows = _window_text(
                parent_text,
                target_characters=child_characters,
                overlap_characters=overlap_characters,
            )
            if len(child_windows) == 1:
                drafts.append(
                    ChunkDraft(
                        local_key=_key(
                            "leaf", segment_index, parent_index, parent_text
                        ),
                        text=parent_text,
                        page_number=segment.page_number,
                        section=segment.section,
                        parent_local_key=None,
                        kind="leaf",
                    )
                )
                continue
            parent_key = _key("parent", segment_index, parent_index, parent_text)
            drafts.append(
                ChunkDraft(
                    local_key=parent_key,
                    text=parent_text,
                    page_number=segment.page_number,
                    section=segment.section,
                    parent_local_key=None,
                    kind="parent",
                )
            )
            for child_index, child_text in enumerate(child_windows):
                drafts.append(
                    ChunkDraft(
                        local_key=_key(
                            "child",
                            segment_index,
                            parent_index * 10_000 + child_index,
                            child_text,
                        ),
                        text=child_text,
                        page_number=segment.page_number,
                        section=segment.section,
                        parent_local_key=parent_key,
                        kind="child",
                    )
                )
    return tuple(drafts)
