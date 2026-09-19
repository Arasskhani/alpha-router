#!/usr/bin/env python3
"""Rewrite ``var(--x, <fallback>)`` to ``var(--x)`` wherever ``--x`` is defined.

A fallback on a token the stylesheet defines is a second, competing definition
that no theme controls. Before this ran, ``--danger`` had drifted to four
different reds through its fallbacks alone. Run after adding a token, and let
``styles.tokens.test.ts`` keep it that way.

Handles nested fallbacks (``var(--a, var(--b, #fff))``) by matching balanced
parentheses rather than a regex over the whole value. Leaves a token alone when
it is *not* defined anywhere, so the gate - not this script - decides what a
phantom token is.

    python scripts/codemods/strip-token-fallbacks.py [--check] frontend/src/styles.css ...
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFINITION = re.compile(r"(?:^|[{;\s])(--[a-zA-Z0-9-]+)\s*:")
INLINE_DEFINITION = re.compile(r"""["'`](--[a-zA-Z0-9-]+)["'`]\s*(?:as\s+\w+\s*)?[:\]]""")


def defined_tokens(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*"):
        if path.suffix == ".css":
            names.update(DEFINITION.findall(path.read_text(encoding="utf-8")))
        elif path.suffix in {".ts", ".tsx"} and not path.name.endswith((".test.ts", ".test.tsx")):
            names.update(INLINE_DEFINITION.findall(path.read_text(encoding="utf-8")))
    return names


def strip(text: str, defined: set[str]) -> tuple[str, int]:
    """Return the rewritten text and how many fallbacks were removed."""

    out: list[str] = []
    i = 0
    removed = 0
    while True:
        start = text.find("var(", i)
        if start == -1:
            out.append(text[i:])
            break
        out.append(text[i:start])
        # find the matching close paren for this var(
        depth = 0
        j = start
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner = text[start + 4 : j]
        match = re.match(r"\s*(--[a-zA-Z0-9-]+)\s*(,\s*(.*))?$", inner, re.S)
        if match and match.group(2) is not None and match.group(1) in defined:
            out.append(f"var({match.group(1)})")
            removed += 1
        else:
            # recurse into the fallback so nested vars are handled
            rewritten, n = strip(inner, defined) if match and match.group(2) else (inner, 0)
            removed += n
            out.append(f"var({rewritten})")
        i = j + 1
    return "".join(out), removed


def main(argv: list[str]) -> int:
    check = "--check" in argv
    files = [Path(a) for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    defined = defined_tokens(root)
    total = 0
    for path in files:
        before = path.read_text(encoding="utf-8")
        after, removed = strip(before, defined)
        total += removed
        if removed and not check:
            path.write_text(after, encoding="utf-8")
        print(f"{path}: {removed} fallback{'s' if removed != 1 else ''} {'would be ' if check else ''}removed")
    if check and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
