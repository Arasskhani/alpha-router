#!/usr/bin/env python3
"""Pair each ``<label>`` with the control that follows it.

jsx-a11y/label-has-associated-control fires when a <label> neither wraps a
control nor points at one with htmlFor. The common shape in this codebase is

    <label>Name</label>
    <input className="input-block" ... />

which reads fine and is inaccessible: a screen reader announces an unlabelled
field, and clicking the text does nothing. The fix is mechanical - an id on
the control, htmlFor on the label - and there were 88 of them, so it is a
script, not an afternoon.

What it pairs: a single-line <label> whose content is plain text (or a text
node plus one {expression}), immediately followed - after whitespace or a
comment - by <input, <select or <textarea that has no id yet. Everything else
is listed as skipped for a person to look at: wrapping labels, labels whose
control is not the next sibling, controls that already carry an id.

Ids are ``<component>-<label-text>`` slugs, unique within the file. Stable,
readable in the DOM, and no hook to thread through a component.

    python scripts/codemods/pair-labels.py [--check] frontend/src/**/*.tsx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LABEL = re.compile(r"""<label(?P<attrs>(?:\s+[^<>]*?)?)>(?P<text>[^<>{}]*?(?:\{[^{}]*\})?[^<>{}]*?)</label>""")
CONTROL_START = re.compile(r"<(input|select|textarea)\b")


def slug(text: str) -> str:
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:40] or "field"


def component_slug(path: Path) -> str:
    return slug(re.sub(r"(?<!^)(?=[A-Z])", "-", path.stem))


def find_control_after(source: str, pos: int) -> tuple[int, int, str] | None:
    """(start, end_of_open_tag, tag) for the next JSX element if it is a control."""

    i = pos
    while i < len(source):
        # skip whitespace and JSX comments
        m = re.match(r"\s*(\{/\*.*?\*/\}\s*)*", source[i:], re.S)
        i += m.end() if m else 0
        if source.startswith("<", i):
            ctl = CONTROL_START.match(source, i)
            if not ctl:
                return None
            # find the end of the opening tag, respecting {...} and quotes
            depth = 0
            j = ctl.end()
            in_str: str | None = None
            while j < len(source):
                c = source[j]
                if in_str:
                    if c == in_str:
                        in_str = None
                elif c in "\"'":
                    in_str = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                elif c == ">" and depth == 0:
                    return i, j, ctl.group(1)
                j += 1
            return None
        return None
    return None


def rewrite(path: Path, source: str) -> tuple[str, int, list[str]]:
    prefix = component_slug(path)
    used: set[str] = set(re.findall(r'\bid="([^"]+)"', source))
    out: list[str] = []
    i = 0
    paired = 0
    skipped: list[str] = []
    while True:
        m = LABEL.search(source, i)
        if not m:
            out.append(source[i:])
            break
        out.append(source[i : m.start()])
        attrs, text = m.group("attrs") or "", m.group("text")
        line = source.count("\n", 0, m.start()) + 1
        if "htmlFor=" in attrs:
            out.append(m.group(0))
            i = m.end()
            continue
        found = find_control_after(source, m.end())
        if not found:
            skipped.append(f"{path}:{line}: <label>{text.strip()[:30]!r} is not followed by a control")
            out.append(m.group(0))
            i = m.end()
            continue
        c_start, c_tag_end, tag = found
        open_tag = source[c_start:c_tag_end]
        if re.search(r"\bid=", open_tag):
            skipped.append(f"{path}:{line}: <{tag}> after <label>{text.strip()[:30]!r} already has an id")
            out.append(m.group(0))
            i = m.end()
            continue
        base = f"{prefix}-{slug(text)}"
        ident, n = base, 2
        while ident in used:
            ident, n = f"{base}-{n}", n + 1
        used.add(ident)
        out.append(f'<label{attrs} htmlFor="{ident}">{text}</label>')
        out.append(source[m.end() : c_start])
        out.append(f"<{tag} id=\"{ident}\"" + source[c_start + 1 + len(tag) : c_tag_end])
        i = c_tag_end
        paired += 1
    return "".join(out), paired, skipped


def main(argv: list[str]) -> int:
    check = "--check" in argv
    files = [Path(a) for a in argv if not a.startswith("--")]
    total = 0
    all_skipped: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        rewritten, paired, skipped = rewrite(path, source)
        all_skipped.extend(skipped)
        if paired:
            total += paired
            print(f"{path}: {paired} paired")
            if not check:
                path.write_text(rewritten, encoding="utf-8")
    for line in all_skipped:
        print("skipped", line)
    print(f"{total} label(s) {'would be ' if check else ''}paired, {len(all_skipped)} skipped for a person")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
