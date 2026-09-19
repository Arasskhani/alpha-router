#!/usr/bin/env bash
# publish-images has had `if: $CI_COMMIT_TAG` since it was written, and the
# workflow rules never started a pipeline for a tag - so pushing v1.0.5 built
# nothing, and every release image was a manual click on main. The tag rule in
# workflow.rules is what makes the release path real; this keeps it there.
#
# No yaml parser in the harness image: grep the two facts.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CI="$REPO/.gitlab-ci.yml"
pass=0; fail=0
check() { if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }

workflow_block="$(awk '/^workflow:/{f=1} f&&/^[^ ]/&&!/^workflow:/{f=0} f' "$CI")"

check "a v* tag starts a pipeline" 'grep -qE "CI_COMMIT_TAG\s*=~\s*/\^v" <<<"$workflow_block"'
check "the tag rule is anchored to a semantic version" 'grep -qE "\^v\\\\d\+\\\\\.\\\\d\+\\\\\.\\\\d\+" <<<"$workflow_block"'
check "publish-images still keys on the tag" 'awk "/^publish-images:/{f=1} f&&/^[^ ]/&&!/^publish-images:/{f=0} f" "$CI" | grep -q "if: \$CI_COMMIT_TAG"'
stages="$(awk '/^stages:/{f=1;next} f&&/^[^ ]/{f=0} f{gsub(/^ *- */,"");print}' "$CI" | tr '\n' ' ')"
check "publish runs after verify (stage order: $stages)" '[[ "$stages" =~ ^verify\ .*publish ]]'

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
