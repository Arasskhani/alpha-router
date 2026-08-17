"""Deterministic prompt-injection and secret indicators for ingested text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyMatch:
    rule_id: str
    severity: str
    excerpt: str


@dataclass(frozen=True)
class KnowledgeSafetyResult:
    status: str
    score: int
    matches: tuple[SafetyMatch, ...]


_RULES: tuple[tuple[str, str, int, re.Pattern[str]], ...] = (
    (
        "override-instructions",
        "high",
        5,
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b.{0,80}"
            r"\b(?:previous|prior|system|developer|safety)\b.{0,40}\b(?:instruction|prompt|rule)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "reveal-system-prompt",
        "high",
        5,
        re.compile(
            r"\b(?:reveal|show|print|repeat|extract|leak)\b.{0,80}"
            r"\b(?:system prompt|developer message|hidden instruction|secret|api key)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "jailbreak-role",
        "medium",
        3,
        re.compile(
            r"\b(?:jailbreak|developer mode|do anything now|DAN|unfiltered mode)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool-coercion",
        "medium",
        3,
        re.compile(
            r"\b(?:call|invoke|execute|run)\b.{0,50}"
            r"\b(?:tool|function|shell|command|webhook)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "prompt-boundary-spoof",
        "medium",
        2,
        re.compile(
            r"(?:<\|(?:system|assistant|developer)\|>|"
            r"\[(?:system|developer)\s*(?:message|instruction)?\])",
            re.IGNORECASE,
        ),
    ),
    (
        "private-key",
        "high",
        5,
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "credential-assignment",
        "medium",
        3,
        re.compile(
            r"\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\b"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}",
            re.IGNORECASE,
        ),
    ),
)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("\x00", " ")


def scan_knowledge_text(texts: tuple[str, ...]) -> KnowledgeSafetyResult:
    matches: list[SafetyMatch] = []
    score = 0
    for raw_text in texts:
        text = _normalize(raw_text)
        for rule_id, severity, weight, pattern in _RULES:
            match = pattern.search(text)
            if match is None:
                continue
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            excerpt = re.sub(r"\s+", " ", text[start:end]).strip()[:300]
            matches.append(
                SafetyMatch(rule_id=rule_id, severity=severity, excerpt=excerpt)
            )
            score += weight
            if len(matches) >= 25:
                break
        if len(matches) >= 25:
            break
    if any(match.severity == "high" for match in matches):
        status = "blocked"
    elif score >= 3:
        status = "review"
    else:
        status = "clean"
    return KnowledgeSafetyResult(
        status=status,
        score=score,
        matches=tuple(matches),
    )
