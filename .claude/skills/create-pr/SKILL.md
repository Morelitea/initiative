---
name: create-pr
description: Open a pull request for the current changes, then watch it to green — poll CI until every check completes, surface and fix failures, and drive the Greptile review loop until confidence is high. Use when the user says "make a PR", "open a pull request", "ship this", or asks to watch a PR's CI / review status.
user-invocable: true
---

# /create-pr — Open a PR and babysit it to green

Create a pull request for the working changes, then stay with it: watch CI to
completion, fix what breaks, and run the Greptile review loop until the review
is clean. Do not consider the skill done until every check is green (or the
user tells you to stop).

Repo rules that this skill must honor (from `CLAUDE.md`):
- **PRs target `dev`, never `main`.**
- Commit subjects are imperative, ≤50 chars. **Never** add `Co-Authored-By`
  trailers or mention coding agents.
- Update `CHANGELOG.md` **before** opening the PR for any user-facing feature,
  fix, or breaking change (skip for pure internal refactors). New changes go
  under `## [Unreleased]`, never under an already-released version.

## 1. Pre-flight — get the change into shape

1. `git status` and `git diff --stat` to see what's staged/unstaged. If there
   are no changes at all, stop and tell the user.
2. Run the quality gates for what changed (don't run the whole world if only
   one side changed):
   - Frontend: `cd frontend && pnpm typecheck` and
     `pnpm biome check <changed files>`; run changed tests with
     `./scripts/test-changed.sh`.
   - Backend: `cd backend && ruff check app` and
     `./scripts/test-changed.sh`.
   Fix anything that fails before opening the PR — a red gate locally will be
   red in CI.
3. If the change is user-facing, add a concise `CHANGELOG.md` entry under
   `## [Unreleased]` in the right subsection (Added / Changed / Fixed /
   Security).

## 2. Branch, commit, push

1. Determine the current branch (`git branch --show-current`). If it is `dev`
   or `main`, create a fresh feature branch off it:
   `git checkout -b <type>/<short-kebab-summary>` (e.g. `fix/…`, `feat/…`).
   If already on a feature branch, keep using it.
2. Stage the intended files explicitly and commit. Imperative subject ≤50
   chars; add a body explaining the *why*. **No** `Co-Authored-By`, no agent
   mentions. A pre-commit hook (lint-staged/biome) may run — let it.
3. `git push -u origin <branch>`.

## 3. Open the PR

Create it against `dev` with a structured body:

```bash
gh pr create --base dev --title "<imperative title>" --body "$(cat <<'EOF'
## Problem
<what was wrong / what this enables>

## Changes
- <bullet per notable change, link files as [name](path)>

## Testing
- <exact commands you ran and their result>

Fixes #<issue>   # only if it closes an issue
EOF
)"
```

Capture the PR number from the returned URL.

## 4. Watch CI to completion

Poll until every check finishes. Prefer a bounded `until` loop over repeated
manual checks:

```bash
# Wait for all checks to reach a terminal state (timeout generously).
until [ -z "$(gh pr view <n> --json statusCheckRollup \
  -q '.statusCheckRollup[] | select(.status!="COMPLETED") | .name')" ]; do
  sleep 15
done
```

Then read the rollup:

```bash
gh pr view <n> --json mergeStateStatus,reviewDecision,statusCheckRollup \
  -q '.statusCheckRollup[] | "\(.name): \(.status)/\(.conclusion)"'
```

The CI workflow's jobs on this repo include **Backend Lint & Tests**,
**Frontend Lint & Tests**, and **Check Generated Types**. If any concludes
`FAILURE`:

1. Pull the failing job's log:
   `gh run view --job <jobId> --log-failed | tail -80`
   (get `<jobId>` from the `detailsUrl` in the rollup, or
   `gh run view <runId> --json jobs`).
2. Reproduce and fix locally. Common repo-specific gotchas:
   - **Locale keys**: `locale-keys.test.ts` requires every `en` key be
     mirrored in `de`/`es`/`fr`. Add new keys to all four locale files.
   - **Generated types**: if backend schemas changed, regenerate per
     `CLAUDE.md` (Orval) and commit the output.
3. Commit the fix, `git push`, and **re-watch from the top of this step**.

Repeat until all checks are green.

## 5. Drive the Greptile review loop

Greptile posts an automated review with a **confidence score** and inline
findings. Read them:

```bash
gh pr view <n> --json reviews -q '.reviews[] | select(.author.login|test("greptile";"i")) | .body'
# inline findings:
gh api repos/{owner}/{repo}/pulls/<n>/comments --jq '.[] | {path,line,body}'
```

For each finding: judge whether it's a real issue in scope for this PR.
- **In scope + valid** → fix it (edit, commit, push).
- **Out of scope / false positive** → note why in a brief reply; don't fix.

After addressing a round of feedback, trigger a re-review by posting a bare
mention as a PR comment:

```bash
gh pr comment <n> --body "@greptile"
```

Wait for the new Greptile review, then re-read. **Aim for 5/5 confidence.**
Accept 4/5 only if the remaining findings are genuinely out of scope for this
PR. Loop (fix → `@greptile` → re-read) until you reach that bar.

## 6. Report

Summarize for the user:
- PR URL and number.
- Final check status (table: check → pass/fail).
- Greptile confidence score and any findings you intentionally left unaddressed
  (with the reason).
- `mergeStateStatus` — if it's `BLOCKED` only on `REVIEW_REQUIRED`, say so:
  all automated gates are green and it's waiting on a human approval
  (@jordandrako / @LeeJMorel), which this skill cannot self-approve.

## Notes on pacing

- CI on this repo takes a couple of minutes per run; a 15s poll with a
  generous timeout (e.g. 420000ms) is reasonable.
- If the user wants to walk away, you can run the wait loop in the background
  and report when it settles rather than blocking the session.
- Never fabricate a check result — only report statuses you actually read from
  `gh`.
