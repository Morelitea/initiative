#!/usr/bin/env bash
# Exercises scripts/git-identity-guard.sh against the ways git can be told to
# use an identity other than the configured one. Run it directly:
#   ./scripts/git-identity-guard_test.sh
set -u

# Ignore the machine's own git config so every case is decided by the
# per-test repo alone, and 'unset' genuinely means unset.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

GUARD=$(cd "$(dirname "$0")" && pwd)/git-identity-guard.sh
CONFIGURED=configured@example.com
OTHER=someone-else@example.com
passed=0
failed=0

new_repo() {
  d=$(mktemp -d)
  git init -q "$d"
  git -C "$d" symbolic-ref HEAD refs/heads/main
  git -C "$d" config user.name tester
  git -C "$d" config user.email "$CONFIGURED"
  mkdir -p "$d/hooks"
  for hook in pre-commit pre-merge-commit; do
    printf '#!/usr/bin/env sh\nset -e\n. "%s"\n' "$GUARD" > "$d/hooks/$hook"
    chmod +x "$d/hooks/$hook"
  done
  git -C "$d" config core.hooksPath ./hooks
  echo "$d"
}

check() {
  description=$1 expected=$2 actual=$3
  if [ "$expected" = "$actual" ]; then
    printf '  ok    %s\n' "$description"
    passed=$((passed + 1))
  else
    printf '  FAIL  %s (expected commit %s, got %s)\n' \
      "$description" "$expected" "$actual"
    failed=$((failed + 1))
  fi
}

# Returns "allowed" or "refused" for a commit attempt in repo $1.
attempt() {
  repo=$1; shift
  date > "$repo/file-$RANDOM"
  git -C "$repo" add -A
  if "$@" -C "$repo" commit -qm "commit" >/dev/null 2>&1; then
    echo allowed
  else
    echo refused
  fi
}

echo "git-identity-guard"

r=$(new_repo)
check "configured identity is allowed" allowed "$(attempt "$r" git)"

r=$(new_repo)
check "GIT_AUTHOR_EMAIL override is refused" refused \
  "$(attempt "$r" env GIT_AUTHOR_EMAIL=$OTHER git)"

r=$(new_repo)
check "GIT_COMMITTER_EMAIL override is refused" refused \
  "$(attempt "$r" env GIT_COMMITTER_EMAIL=$OTHER git)"

r=$(new_repo)
check "GIT_CONFIG_PARAMETERS override is refused" refused \
  "$(attempt "$r" env "GIT_CONFIG_PARAMETERS='user.email'='$OTHER'" git)"

# `git -c` is the same channel, reached the way a person would reach it.
r=$(new_repo)
date > "$r/f"; git -C "$r" add -A
if git -c "user.email=$OTHER" -C "$r" commit -qm c >/dev/null 2>&1; then
  cmd_result=allowed
else
  cmd_result=refused
fi
check "git -c user.email override is refused" refused "$cmd_result"

r=$(new_repo)
git -C "$r" config --unset user.email
check "missing user.email is refused" refused "$(attempt "$r" git)"

# Merge commits run pre-merge-commit, not pre-commit.
r=$(new_repo)
attempt "$r" git >/dev/null
git -C "$r" checkout -qb side
date > "$r/side-file"; git -C "$r" add -A
git -C "$r" commit -qm side >/dev/null 2>&1
git -C "$r" checkout -q main
date > "$r/main-file"; git -C "$r" add -A
git -C "$r" commit -qm main >/dev/null 2>&1
if git -C "$r" -c "user.email=$CONFIGURED" merge --no-ff -m merge side >/dev/null 2>&1
then merge_clean=allowed; else merge_clean=refused; fi
check "clean merge commit is allowed" allowed "$merge_clean"

r=$(new_repo)
attempt "$r" git >/dev/null
git -C "$r" checkout -qb side
date > "$r/side-file"; git -C "$r" add -A
git -C "$r" commit -qm side >/dev/null 2>&1
git -C "$r" checkout -q main
date > "$r/main-file"; git -C "$r" add -A
git -C "$r" commit -qm main >/dev/null 2>&1
if GIT_AUTHOR_EMAIL=$OTHER git -C "$r" merge --no-ff -m merge side >/dev/null 2>&1
then merge_bad=allowed; else merge_bad=refused; fi
check "merge under an override is refused" refused "$merge_bad"

echo
echo "  $passed passed, $failed failed"
[ "$failed" -eq 0 ]
