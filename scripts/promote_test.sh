#!/usr/bin/env bash
# Guards the branch-name contract between promote.sh and tag-release.yml.
#
# tag-release.yml tags a merged PR only when its head branch carries a specific
# prefix, and reads the version from what follows. promote.sh names the branch.
# Nothing else connects the two: name a release branch anything else and the
# merge lands a bumped VERSION on main with no tag, no Docker image and no
# GitHub Release — while every other check stays green.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMOTE="$ROOT/scripts/promote.sh"
WORKFLOW="$ROOT/.github/workflows/tag-release.yml"

failures=0
fail() { echo "FAIL: $*" >&2; failures=$((failures + 1)); }
pass() { echo "ok: $*"; }

# The prefix the workflow gates on, read from the workflow itself.
PREFIX=$(sed -n "s/.*startsWith(github.event.pull_request.head.ref, '\([^']*\)').*/\1/p" \
    "$WORKFLOW" | head -1)
[[ -n "$PREFIX" ]] || { echo "FAIL: no startsWith() branch gate found in $WORKFLOW" >&2; exit 1; }
pass "tag-release.yml gates on prefix '$PREFIX'"

# The workflow must strip the same prefix it gated on, or it tags the wrong version.
if grep -qF "\${BRANCH#$PREFIX}" "$WORKFLOW"; then
    pass "tag-release.yml derives the version by stripping '$PREFIX'"
else
    fail "tag-release.yml gates on '$PREFIX' but does not strip it to derive the version"
fi

# Every branch promote.sh names after a new version must carry that prefix —
# those are the branches whose merge is meant to cut a release.
mapfile -t VERSION_BRANCHES < <(grep -n 'branch="[^"]*\$new_version[^"]*"' "$PROMOTE")
if [[ ${#VERSION_BRANCHES[@]} -eq 0 ]]; then
    fail "no version-bearing branch names found in promote.sh — has the naming moved?"
fi
for entry in "${VERSION_BRANCHES[@]}"; do
    line_no=${entry%%:*}
    name=$(sed -n 's/.*branch="\([^"]*\)".*/\1/p' <<<"$entry")
    if [[ "$name" == "$PREFIX"* ]]; then
        pass "promote.sh:$line_no names '$name'"
    else
        fail "promote.sh:$line_no names '$name', which tag-release.yml will not tag (needs '$PREFIX' prefix)"
    fi
done

# The unbumped cherry-pick ships no version, so it must NOT look like a release.
if grep -q 'branch="hotfix/\$DATE"' "$PROMOTE"; then
    pass "promote.sh keeps an unversioned hotfix branch that does not trigger a release"
else
    fail "promote.sh no longer has the unversioned 'hotfix/\$DATE' branch"
fi

# Every generated API file embeds the VERSION in its header, so any mode that
# bumps the version has to restamp them. CI's "Check Generated Types" job
# filters on backend/ and orval config, so a bump touching neither skips the
# job and the stale headers ship green.
body_of() {
    awk -v fn="$1" '$0 ~ "^"fn"\\(\\) \\{" {inside=1; next} inside && /^\}/ {exit} inside {print}' "$PROMOTE"
}
for fn in do_release do_cherry_pick; do
    body=$(body_of "$fn")
    if [[ -z "$body" ]]; then
        fail "could not read the body of $fn in promote.sh"
    elif grep -q 'regenerate_api_types' <<<"$body"; then
        pass "$fn regenerates the committed API types"
    else
        fail "$fn bumps the version but never calls regenerate_api_types — the generated headers would ship stale"
    fi
done

if [[ $failures -gt 0 ]]; then
    echo "" >&2
    echo "$failures check(s) failed." >&2
    exit 1
fi
echo ""
echo "All release branch-name checks passed."
