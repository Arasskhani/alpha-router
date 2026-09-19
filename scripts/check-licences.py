#!/usr/bin/env python3
"""Fail when a dependency arrives under a licence NOTICE does not account for.

The claim in NOTICE is: everything not named there is permissive. This script
checks that claim against what is actually installed, on every pipeline, so a
copyleft or source-available package cannot arrive with an ordinary version bump
and sit unnoticed until somebody asks.

Three outcomes per package:

* permissive (MIT, BSD, Apache, ISC, PSF, MPL-only-as-file, ...): fine.
* weak copyleft (LGPL, MPL, EPL, CDDL) or unknown: fine **only if NOTICE names
  the package**. That is the point of the NOTICE section - it is where the
  obligation is written down.
* strong copyleft or source-available (GPL, AGPL, SSPL, RSAL, BUSL, Commons
  Clause, "proprietary"): fail, whether NOTICE names it or not. Nothing under
  those terms belongs linked into this process; it needs a decision, not a
  line in a file.

Usage:
    check-licences.py python  <requirements-file> [...]   # needs pip-licenses
    check-licences.py node    <path-to-frontend>          # reads node_modules

Python packages are read from the *installed* environment, filtered to the
names in the given requirements files, so the check sees exactly what the image
will contain.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE = (ROOT / "NOTICE").read_text(encoding="utf-8").lower()
OVERRIDES: dict[str, dict[str, str]] = {
    name.lower(): entry
    for name, entry in json.loads(
        (ROOT / "scripts" / "licence-overrides.json").read_text(encoding="utf-8")
    ).items()
    if not name.startswith("_")
}

# Word-boundary patterns, not substrings: "IMPLIED" contains "mpl" and a full
# MIT text is a perfectly ordinary value for the License field.
_PERMISSIVE = re.compile(
    r"\b(mit|bsd|apache|isc|psf|python software foundation|unlicense|zlib|0bsd|public domain|cc0"
    r"|wtfpl|blueoak|hpnd|historical permission|artistic|boost|postgresql|ofl|sil open font)\b"
)
_WEAK = re.compile(
    r"\b(lgpl\S*|lesser general public license[^;,]*|library general public license[^;,]*|library or lesser general public license[^;,]*"
    r"|mpl(-?\d(\.\d)?)?|mozilla public license[^;,]*|epl(-?\d(\.\d)?)?|eclipse public license[^;,]*"
    r"|cddl(-?\d(\.\d)?)?|osl(-?\d(\.\d)?)?|cpal(-?\d(\.\d)?)?|eupl(-?\d(\.\d)?)?)\b"
)
_STRONG = re.compile(
    r"\b(agpl\S*|affero|gpl\S*|general public license|sspl\S*|server side public|rsal\S*|redis source available"
    r"|busl\S*|business source|commons clause|proprietary|commercial|elastic license)\b"
)


def classify(licence: str) -> str:
    text = " ".join(licence.lower().split())
    weak = bool(_WEAK.search(text))
    without_weak = _WEAK.sub("", text)
    if _STRONG.search(without_weak):
        return "strong"
    if weak:
        return "weak"
    if _PERMISSIVE.search(text):
        return "permissive"
    return "unknown"


def named_in_notice(package: str) -> bool:
    return (
        re.search(rf"^\s*{re.escape(package.lower())}\s", NOTICE, re.MULTILINE)
        is not None
    )


def report(rows: list[tuple[str, str, str]]) -> int:
    """rows: (package, version, licence). Returns the exit code."""
    failures: list[str] = []
    noted: list[str] = []
    for package, version, licence in sorted(rows, key=lambda r: r[0].lower()):
        override = OVERRIDES.get(package.lower().replace("_", "-"))
        if override:
            print(
                "override",
                f"{package} {version}: metadata says {licence!r}, LICENSE file says {override['licence']!r}",
            )
            licence = override["licence"]
        kind = classify(licence)
        if kind == "permissive":
            continue
        if kind == "strong":
            failures.append(
                f"{package} {version}: {licence!r} - strong copyleft or source-available; not acceptable linked in"
            )
        elif named_in_notice(package):
            noted.append(f"{package} {version}: {licence!r} - {kind}, named in NOTICE")
        else:
            failures.append(
                f"{package} {version}: {licence!r} - {kind}, and NOTICE does not name it"
            )
    for line in noted:
        print("noted   ", line)
    for line in failures:
        print("FAIL    ", line)
    print(
        f"{len(rows)} packages checked, {len(noted)} covered by NOTICE, {len(failures)} failures"
    )
    return 1 if failures else 0


def _requirement_names(files: list[str]) -> set[str]:
    names: set[str] = set()
    for file in files:
        for raw in Path(file).read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "\\")):
                continue
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if match:
                names.add(match.group(1).lower().replace("_", "-"))
    return names


def python(files: list[str]) -> int:
    wanted = _requirement_names(files)
    out = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--format=json", "--from=mixed"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rows = []
    for item in json.loads(out):
        name = item["Name"].lower().replace("_", "-")
        if name in wanted:
            rows.append((item["Name"], item["Version"], item["License"]))
    missing = wanted - {r[0].lower().replace("_", "-") for r in rows}
    code = report(rows)
    if missing:
        # An unchecked package is a hole in the claim, not a pass.
        print("FAIL     not installed, so not checked:", ", ".join(sorted(missing)))
        return 1
    return code


def node(frontend: str) -> int:
    """Production dependencies only: what reaches the browser, not the build tools.

    The obligation that NOTICE discharges is about what is *distributed*. eslint
    plugins, the bundler and browserslist data never leave the build machine,
    so they are out of scope here the same way the CI runner image is.
    """

    listing = subprocess.run(
        ["npm", "ls", "--omit=dev", "--all", "--parseable"],
        cwd=frontend,
        capture_output=True,
        text=True,
        check=False,  # npm ls exits non-zero on peer warnings; the listing is still complete
    ).stdout
    rows = []
    for path in sorted(
        {line.strip() for line in listing.splitlines() if "/node_modules/" in line}
    ):
        manifest = Path(path) / "package.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        licence = data.get("license") or data.get("licence") or ""
        if isinstance(licence, dict):
            licence = licence.get("type", "")
        if isinstance(licence, list):
            licence = " OR ".join(
                x.get("type", "") if isinstance(x, dict) else str(x) for x in licence
            )
        rows.append(
            (
                data.get("name", Path(path).name),
                str(data.get("version", "")),
                str(licence),
            )
        )
    if not rows:
        print(
            "FAIL     npm ls returned no production dependencies - is node_modules installed?"
        )
        return 1
    return report(rows)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in {"python", "node"}:
        print(__doc__)
        sys.exit(2)
    sys.exit(python(sys.argv[2:]) if sys.argv[1] == "python" else node(sys.argv[2]))
