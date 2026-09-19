#!/usr/bin/env python3
"""Add ``role="alert"`` to the elements that show an error message.

An error rendered as <p className="alert alert-error"> is visible; it is not
*announced*. A screen-reader user who submits a form and gets a red paragraph
somewhere above the button hears nothing. role="alert" makes the browser read
it out the moment it appears, which is what these elements are for.

Targets the four class names this codebase uses for inline errors and leaves
anything that already has a role alone.

    python scripts/codemods/alert-role-on-errors.py [--check] frontend/src/**/*.tsx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ERROR_CLASSES = ("alert alert-error", "error", "form-error", "settings-error")
PATTERN = re.compile(
    r"<(p|div|span)(\s+className=\"(?:" + "|".join(re.escape(c) for c in ERROR_CLASSES) + r")\")(?P<rest>[^>]*)>"
)


def rewrite(source: str) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        if "role=" in m.group("rest"):
            return m.group(0)
        count += 1
        return f'<{m.group(1)}{m.group(2)} role="alert"{m.group("rest")}>'

    return PATTERN.sub(repl, source), count


def main(argv: list[str]) -> int:
    check = "--check" in argv
    total = 0
    for arg in argv:
        if arg.startswith("--"):
            continue
        path = Path(arg)
        source = path.read_text(encoding="utf-8")
        rewritten, n = rewrite(source)
        if n:
            total += n
            print(f"{path}: {n}")
            if not check:
                path.write_text(rewritten, encoding="utf-8")
    print(f"{total} error element(s) {'would get' if check else 'given'} role=\"alert\"")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
