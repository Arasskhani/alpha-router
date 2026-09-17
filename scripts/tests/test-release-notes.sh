#!/usr/bin/env bash
# scripts/release-notes.py turns the commits behind a tag into the GitHub
# Release body (.github/workflows/release.yml publishes it on a tag push).
#
# Real local repositories, no network. The cases are the ones this project
# actually produces: a normal range, a first release, subjects that predate the
# commit-msg hook, a breaking change, and a tag range that spans a rewritten
# history - which this repository has had, and which is why the previous tag is
# chosen by version order rather than by walking ancestry.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NOTES="$REPO/scripts/release-notes.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

fail() { echo "FAIL: $*" >&2; exit 1; }
contains() { grep -qF -- "$2" <<<"$1" || fail "$3"; }
lacks() { grep -qF -- "$2" <<<"$1" && fail "$3" || true; }

commit() { echo "$RANDOM" > "$1/f"; git -C "$1" add -A; git -C "$1" commit -qm "$2"; }

# --- a normal release range --------------------------------------------------
R="$TMP/normal"; mkdir -p "$R"; git -C "$R" init -q -b main
commit "$R" "feat: the very first thing"
git -C "$R" tag v1.0.0
commit "$R" "feat(admin-logs): serve the administrative audit trail"
commit "$R" "fix(config): treat an empty value as unset"
commit "$R" "docs(admin-guide): explain where the version comes from"
commit "$R" "chore: bump a thing"
commit "$R" "fix(rbac): stop an escalation"
git -C "$R" tag v1.1.0

out="$(python3 "$NOTES" v1.1.0 --repo-dir "$R" --repo-url https://example.invalid/o/r)"
contains "$out" "## Features"                         "no Features section"
contains "$out" "**admin-logs**: serve the administrative audit trail" "feature missing or scope dropped"
contains "$out" "## Fixes"                            "no Fixes section"
contains "$out" "**config**: treat an empty value as unset" "fix missing"
contains "$out" "## Security & hardening"             "an rbac fix should be surfaced separately"
contains "$out" "**rbac**: stop an escalation"        "rbac fix missing"
contains "$out" "## Documentation"                    "no Documentation section"
contains "$out" "## Build, CI & chores"               "chore was dropped"
contains "$out" "5 commit(s) since **v1.0.0**"        "wrong commit count or previous tag"
contains "$out" "compare/v1.0.0...v1.1.0"             "no compare link"
lacks "$out" "the very first thing"                   "a commit from before the previous tag leaked in"
echo "ok: groups a normal range by type, keeps scopes, counts the range"

# Features must come before Fixes, and breaking changes before everything.
[ "$(grep -n '^## ' <<<"$out" | head -1 | cut -d: -f2-)" = "## Features" ] \
  || fail "section order: Features should lead when there is no breaking change"
echo "ok: sections are ordered, most consequential first"

# --- a breaking change ------------------------------------------------------
commit "$R" "feat(rbac)!: remove the legacy role slugs"
git -C "$R" tag v2.0.0
out="$(python3 "$NOTES" v2.0.0 --repo-dir "$R")"
contains "$out" "Breaking changes"                    "a ! subject was not flagged as breaking"
[ "$(grep -n '^## ' <<<"$out" | head -1 | cut -d: -f2-)" = "## ⚠ Breaking changes" ] \
  || fail "breaking changes must be the first section"
echo "ok: a ! subject leads the notes as a breaking change"

# BREAKING CHANGE: in the body counts too, without the !.
commit "$R" "$(printf 'refactor(api): rename a field\n\nBREAKING CHANGE: clients must update.')"
git -C "$R" tag v2.1.0
out="$(python3 "$NOTES" v2.1.0 --repo-dir "$R")"
contains "$out" "Breaking changes"                    "BREAKING CHANGE in the body was not honoured"
echo "ok: BREAKING CHANGE in the body counts as well"

# --- subjects that predate the commit-msg hook -------------------------------
O="$TMP/old"; mkdir -p "$O"; git -C "$O" init -q -b main
commit "$O" "feat: something"
git -C "$O" tag v1.0.0
commit "$O" "Update September 2026"
commit "$O" "Enhance API Log Details"
git -C "$O" tag v1.0.1
out="$(python3 "$NOTES" v1.0.1 --repo-dir "$O")"
contains "$out" "## Other changes"                    "non-conforming subjects were dropped"
contains "$out" "Update September 2026"               "a non-conforming commit vanished from the notes"
contains "$out" "2 commit(s) since"                   "non-conforming commits were not counted"
echo "ok: a subject the hook would reject is still listed, never silently dropped"

# --- a first release ---------------------------------------------------------
F="$TMP/first"; mkdir -p "$F"; git -C "$F" init -q -b main
commit "$F" "feat: initial"
commit "$F" "fix: something"
git -C "$F" tag v0.1.0
out="$(python3 "$NOTES" v0.1.0 --repo-dir "$F")"
contains "$out" "First release"                       "a tag with no predecessor should say so"
contains "$out" "2 commit(s)"                         "a first release should list everything"
lacks "$out" "compare/"                               "there is nothing to compare a first release against"
echo "ok: the first release describes itself rather than failing"

# --- a rewritten history, which this repository has had ----------------------
# v1.0.0 sits on the old history; v1.1.0 on an unrelated rewritten one. An
# ancestry walk (git describe --abbrev=0 v1.1.0^) finds no earlier tag here.
W="$TMP/rewritten"; mkdir -p "$W"; git -C "$W" init -q -b main
commit "$W" "feat: before the rewrite"
git -C "$W" tag v1.0.0
git -C "$W" checkout -q --orphan rewritten
git -C "$W" add -A; git -C "$W" commit -qm "feat: after the rewrite"
commit "$W" "fix: something later"
git -C "$W" branch -qM main
git -C "$W" tag v1.1.0

if git -C "$W" describe --abbrev=0 --tags "v1.1.0^" >/dev/null 2>&1; then
  fail "harness assumption broken: the rewritten history should have no reachable earlier tag"
fi
out="$(python3 "$NOTES" v1.1.0 --repo-dir "$W")"
contains "$out" "since **v1.0.0**"                    "the previous tag was not found across a rewritten history"
contains "$out" "after the rewrite"                   "commits on the new history are missing"
echo "ok: finds the previous tag by version order, across a rewritten history"

# --- a pre-release tag is not a release --------------------------------------
git -C "$R" tag v3.0.0-rc1
if python3 "$NOTES" v3.0.0-rc1 --repo-dir "$R" >/dev/null 2>&1; then
  fail "a pre-release tag should be refused, as latest_release_tag refuses it"
fi
out="$(python3 "$NOTES" v2.1.0 --repo-dir "$R")"
lacks "$out" "v3.0.0-rc1"                             "a pre-release tag leaked into the range"
echo "ok: a pre-release tag is neither a release nor a boundary"

echo "PASS: test-release-notes.sh"
