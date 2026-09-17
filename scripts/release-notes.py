#!/usr/bin/env python3
"""Release notes for one tag, from the Conventional Commits behind it.

The tag is this project's source of truth: it decides which code a host
deploys (``latest_release_tag`` in scripts/lib/stack.sh) and what the product
calls itself (``resolve_app_version``). This makes it decide the release notes
too, so there is nothing to keep in sync by hand.

    scripts/release-notes.py v1.0.4            # notes for that tag
    scripts/release-notes.py v1.0.4 --since v1.0.3

Commit subjects are already constrained: scripts/check-commit-message.py runs
in the commit-msg hook and rejects anything that is not
``<type>(<scope>)?(!)?: <description>``. Subjects that predate the hook still
appear, under "Other changes" - listing them is the point, since a release note
that silently drops commits is worse than an untidy one.

Prints markdown on stdout.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)

SUBJECT_RE = re.compile(
    r"^(?P<type>" + "|".join(TYPES) + r")"
    r"(\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?"
    r"(?P<bang>!)?: "
    r"(?P<desc>\S.*)$"
)

#: Same shape as latest_release_tag in scripts/lib/stack.sh: three numbers, a
#: leading v, nothing else. A pre-release tag is deliberately not a release.
RELEASE_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

#: Order matters: this is the order sections appear in the notes, most
#: consequential first. Types not listed here fall into "Other changes"; none
#: are hidden, because an operator deciding whether to upgrade should see
#: everything that is in the release.
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Features", ("feat",)),
    ("Fixes", ("fix",)),
    ("Performance", ("perf",)),
    ("Security & hardening", ()),  # filled by scope, see _section_for
    ("Documentation", ("docs",)),
    ("Refactoring", ("refactor", "style")),
    ("Build, CI & chores", ("build", "ci", "chore", "test", "revert")),
)

_TYPE_TO_SECTION = {t: title for title, types in SECTIONS for t in types}


class Commit:
    def __init__(self, sha: str, subject: str, body: str) -> None:
        self.sha = sha
        self.subject = subject
        self.body = body
        match = SUBJECT_RE.match(subject)
        self.type = match["type"] if match else None
        self.scope = match["scope"] if match else None
        self.description = match["desc"] if match else subject
        self.breaking = bool(match and match["bang"]) or "BREAKING CHANGE:" in body

    def bullet(self, short_sha: bool = True) -> str:
        text = f"**{self.scope}**: {self.description}" if self.scope else self.description
        return f"- {text} ({self.sha[:7]})" if short_sha else f"- {text}"


def _git(*args: str, cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def release_tags(cwd: str | None = None) -> list[str]:
    """Every release tag, oldest first, ordered by version not by date."""
    tags = [t for t in _git("tag", "--list", cwd=cwd).split() if RELEASE_TAG_RE.match(t)]
    return sorted(tags, key=lambda t: tuple(int(n) for n in RELEASE_TAG_RE.match(t).groups()))


def previous_release_tag(tag: str, cwd: str | None = None) -> str | None:
    """The newest release tag below ``tag``, by version order.

    Deliberately not ``git describe --abbrev=0 <tag>^``, which walks ancestry.
    This repository has had its history rewritten and force-pushed once; after
    that, tags on either side of the rewrite are not each other's ancestors and
    an ancestry walk finds the wrong tag, or none.
    """
    match = RELEASE_TAG_RE.match(tag)
    if not match:
        raise SystemExit(f"'{tag}' is not a release tag (expected vMAJOR.MINOR.PATCH)")
    current = tuple(int(n) for n in match.groups())
    below = [t for t in release_tags(cwd) if tuple(int(n) for n in RELEASE_TAG_RE.match(t).groups()) < current]
    return below[-1] if below else None


def commits_between(since: str | None, tag: str, cwd: str | None = None) -> list[Commit]:
    """Commits reachable from ``tag`` but not from ``since``.

    With no previous tag this is every commit, which is what a first release
    should contain.
    """
    span = f"{since}..{tag}" if since else tag
    raw = _git("log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", span, cwd=cwd)
    commits = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, body = (record.split("\x1f") + ["", ""])[:3]
        commits.append(Commit(sha, subject, body))
    return commits


def _section_for(commit: Commit) -> str:
    # A security fix is a fix, but an operator scanning a release wants it
    # first; the scope is the only signal the convention gives us.
    if commit.scope in {"security", "rbac", "audit", "auth"} and commit.type in {
        "fix",
        "feat",
    }:
        return "Security & hardening"
    return _TYPE_TO_SECTION.get(commit.type or "", "Other changes")


def render(tag: str, since: str | None, commits: list[Commit], repo_url: str | None) -> str:
    lines: list[str] = []

    breaking = [c for c in commits if c.breaking]
    if breaking:
        lines.append("## ⚠ Breaking changes")
        lines.append("")
        lines.extend(c.bullet() for c in breaking)
        lines.append("")

    grouped: dict[str, list[Commit]] = {}
    for commit in commits:
        grouped.setdefault(_section_for(commit), []).append(commit)

    order = [title for title, _ in SECTIONS] + ["Other changes"]
    for title in order:
        entries = grouped.get(title)
        if not entries:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(c.bullet() for c in entries)
        lines.append("")

    if not commits:
        lines.append("No changes recorded since the previous release.")
        lines.append("")

    lines.append("---")
    lines.append("")
    if since:
        lines.append(f"{len(commits)} commit(s) since **{since}**.")
        if repo_url:
            lines.append("")
            lines.append(f"[Full diff]({repo_url}/compare/{since}...{tag})")
    else:
        lines.append(f"First release. {len(commits)} commit(s).")
    lines.append("")
    lines.append(
        "Upgrade an existing host with `./scripts/upgrade.sh --prod`; a pinned checkout moves to this tag on its own."
    )
    return "\n".join(lines).rstrip() + "\n"


def repo_url_from_remote(cwd: str | None = None) -> str | None:
    try:
        remote = _git("remote", "get-url", "origin", cwd=cwd).strip()
    except SystemExit:
        return None
    if not remote:
        return None
    remote = remote.removesuffix(".git")
    if remote.startswith("git@"):  # git@github.com:owner/repo
        host, _, path = remote.partition(":")
        return f"https://{host.removeprefix('git@')}/{path}"
    return remote if remote.startswith("http") else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tag", help="the release tag to write notes for, e.g. v1.0.4")
    parser.add_argument("--since", help="previous tag (default: the next release tag below this one)")
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="repository to read (default: current directory)",
    )
    parser.add_argument("--repo-url", default=None, help="project URL for the compare link")
    args = parser.parse_args(argv)

    since = args.since or previous_release_tag(args.tag, args.repo_dir)
    commits = commits_between(since, args.tag, args.repo_dir)
    repo_url = args.repo_url or repo_url_from_remote(args.repo_dir)
    sys.stdout.write(render(args.tag, since, commits, repo_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
