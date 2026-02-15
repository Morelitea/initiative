#!/bin/bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Globals ──────────────────────────────────────────────────────────────────
MODE=""              # promote | release | cherry-pick | rollback
BUMP_TYPE=""         # patch | minor | major | custom
CUSTOM_VERSION=""
CHERRY_SHAS=()
DRY_RUN=false
AUTO_CONFIRM=false
CLEANUP_BRANCH=""
ALLOWED_OWNERS=("jordandrako" "LeeJMorel")
DATE=$(date +%Y-%m-%d)

# ── Helpers ──────────────────────────────────────────────────────────────────
die()  { echo -e "${RED}ERROR: $*${NC}" >&2; exit 1; }
warn() { echo -e "${YELLOW}$*${NC}"; }
info() { echo -e "${GREEN}$*${NC}"; }
dim()  { echo -e "${DIM}$*${NC}"; }

cleanup() {
    if [[ -n "$CLEANUP_BRANCH" ]]; then
        warn "Cleaning up branch $CLEANUP_BRANCH..."
        git checkout dev 2>/dev/null || git checkout main 2>/dev/null || true
        git branch -D "$CLEANUP_BRANCH" 2>/dev/null || true
    fi
}
trap cleanup ERR

confirm() {
    if $AUTO_CONFIRM; then return 0; fi
    local msg="${1:-Continue?}"
    read -rp "$(echo -e "${YELLOW}${msg} [y/N]: ${NC}")" ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

# ── Usage ────────────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: scripts/promote.sh [OPTIONS]

Safely manage promotions from dev to main via pull requests.

Options:
  --patch              Promote + bump patch version (0.29.1 -> 0.29.2)
  --minor              Promote + bump minor version (0.29.1 -> 0.30.0)
  --major              Promote + bump major version (0.29.1 -> 1.0.0)
  --version X.Y.Z      Promote + set explicit version
  --cherry-pick SHA... Cherry-pick specific commits instead of full merge
  --rollback           Revert a release on main
  --dry-run            Show what would happen without making changes
  -y                   Auto-confirm prompts
  -h, --help           Show this help

Examples:
  scripts/promote.sh                        # Promote dev to main (no release)
  scripts/promote.sh --dry-run              # Preview what would be promoted
  scripts/promote.sh --patch                # Promote + patch release
  scripts/promote.sh --minor                # Promote + minor release
  scripts/promote.sh --major                # Promote + major release
  scripts/promote.sh --cherry-pick abc123   # Cherry-pick a hotfix to main
  scripts/promote.sh --rollback             # Revert the latest release
  scripts/promote.sh --rollback --version 0.29.1  # Revert a specific release
EOF
}

# ── Argument parsing ─────────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --patch)  BUMP_TYPE="patch"; shift ;;
            --minor)  BUMP_TYPE="minor"; shift ;;
            --major)  BUMP_TYPE="major"; shift ;;
            --version)
                BUMP_TYPE="custom"
                CUSTOM_VERSION="${2:-}"
                [[ -z "$CUSTOM_VERSION" ]] && die "--version requires an argument (X.Y.Z)"
                shift 2
                ;;
            --cherry-pick)
                MODE="cherry-pick"
                shift
                while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                    CHERRY_SHAS+=("$1")
                    shift
                done
                [[ ${#CHERRY_SHAS[@]} -eq 0 ]] && die "--cherry-pick requires at least one SHA"
                ;;
            --rollback) MODE="rollback"; shift ;;
            --dry-run)  DRY_RUN=true; shift ;;
            -y)         AUTO_CONFIRM=true; shift ;;
            -h|--help)  usage; exit 0 ;;
            *)          die "Unknown option: $1" ;;
        esac
    done

    # Determine mode from flags
    if [[ -z "$MODE" ]]; then
        if [[ -n "$BUMP_TYPE" ]]; then
            MODE="release"
        else
            MODE="promote"
        fi
    fi

    # Cherry-pick can also have a version bump
    if [[ "$MODE" == "cherry-pick" && -n "$BUMP_TYPE" ]]; then
        : # valid combination
    fi
}

# ── Version helpers ──────────────────────────────────────────────────────────
read_version() {
    [[ -f VERSION ]] || die "VERSION file not found (run from repo root)"
    cat VERSION | tr -d '[:space:]'
}

parse_version() {
    local ver="$1"
    [[ "$ver" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || die "Invalid version format: $ver"
    V_MAJOR="${BASH_REMATCH[1]}"
    V_MINOR="${BASH_REMATCH[2]}"
    V_PATCH="${BASH_REMATCH[3]}"
}

calc_new_version() {
    local current="$1"
    parse_version "$current"

    case "$BUMP_TYPE" in
        patch)  echo "${V_MAJOR}.${V_MINOR}.$((V_PATCH + 1))" ;;
        minor)  echo "${V_MAJOR}.$((V_MINOR + 1)).0" ;;
        major)  echo "$((V_MAJOR + 1)).0.0" ;;
        custom)
            [[ "$CUSTOM_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
                || die "Invalid version: $CUSTOM_VERSION (expected X.Y.Z)"
            echo "$CUSTOM_VERSION"
            ;;
    esac
}

# ── Pre-flight checks ───────────────────────────────────────────────────────
preflight() {
    echo -e "${BOLD}Pre-flight checks${NC}"
    echo "─────────────────────────────────────"

    # gh CLI
    command -v gh &>/dev/null || die "gh CLI not found — install from https://cli.github.com"
    gh auth status &>/dev/null || die "gh CLI not authenticated — run 'gh auth login'"
    info "  gh CLI authenticated"

    # Clean working directory
    [[ -z "$(git status --porcelain)" ]] || die "Working directory not clean — commit or stash changes"
    info "  Working directory clean"

    # Fetch latest
    git fetch origin --quiet
    info "  Fetched latest from origin"

    # Check code owner
    local login
    login=$(gh api user --jq '.login' 2>/dev/null) || die "Could not determine GitHub user"
    local is_owner=false
    local login_lower="${login,,}"
    for owner in "${ALLOWED_OWNERS[@]}"; do
        if [[ "${owner,,}" == "$login_lower" ]]; then
            is_owner=true
            break
        fi
    done
    $is_owner || die "User '$login' is not a code owner (allowed: ${ALLOWED_OWNERS[*]})"
    info "  Code owner: $login"

    echo ""
}

check_branch_sync() {
    local branch="$1" remote="origin/$1"

    # Check local branch exists
    git rev-parse --verify "$branch" &>/dev/null \
        || die "Local branch '$branch' not found"

    # Check remote branch exists
    git rev-parse --verify "$remote" &>/dev/null \
        || die "Remote branch '$remote' not found"

    local local_sha remote_sha
    local_sha=$(git rev-parse "$branch")
    remote_sha=$(git rev-parse "$remote")

    if [[ "$local_sha" != "$remote_sha" ]]; then
        die "Local '$branch' ($local_sha) is out of sync with '$remote' ($remote_sha) — pull or push first"
    fi
    info "  $branch synced with origin"
}

check_ci_passing() {
    local branch="$1"
    dim "  Checking CI status on $branch..."
    local status
    status=$(gh api "repos/{owner}/{repo}/commits/$branch/status" --jq '.state' 2>/dev/null) || true

    case "$status" in
        success) info "  CI passing on $branch" ;;
        pending) warn "  CI is still running on $branch — proceed with caution" ;;
        failure) die "CI is failing on $branch — fix before promoting" ;;
        *)
            # Fall back to check-runs if commit status API has no data
            local conclusion
            conclusion=$(gh api "repos/{owner}/{repo}/commits/$branch/check-runs" \
                --jq '[.check_runs[].conclusion] | if length == 0 then "none" elif all(. == "success") then "success" elif any(. == "failure") then "failure" else "pending" end' 2>/dev/null) || true
            case "$conclusion" in
                success) info "  CI passing on $branch" ;;
                none)    warn "  No CI checks found on $branch — proceed with caution" ;;
                pending) warn "  CI is still running on $branch — proceed with caution" ;;
                failure) die "CI is failing on $branch — fix before promoting" ;;
            esac
            ;;
    esac
}

# ── Changelog helpers ────────────────────────────────────────────────────────
check_unreleased_content() {
    [[ -f CHANGELOG.md ]] || die "CHANGELOG.md not found"

    # Extract content between [Unreleased] and the next ## heading
    local content
    content=$(awk '/^## \[Unreleased\]/{found=1; next} /^## \[/{found=0} found{print}' CHANGELOG.md \
        | sed '/^[[:space:]]*$/d')

    if [[ -z "$content" ]]; then
        die "CHANGELOG.md [Unreleased] section is empty — add release notes first"
    fi
    info "  Changelog [Unreleased] has content"
}

stamp_changelog() {
    local version="$1"
    local date="$2"

    # Replace "## [Unreleased]" with "## [Unreleased]\n\n## [X.Y.Z] - YYYY-MM-DD"
    sed -i "s/^## \[Unreleased\]/## [Unreleased]\n\n## [$version] - $date/" CHANGELOG.md
}

preview_changelog() {
    local version="$1"
    echo -e "${CYAN}Changelog preview for $version:${NC}"
    awk '/^## \[Unreleased\]/{found=1; next} /^## \[/{found=0} found{print}' CHANGELOG.md \
        | head -20
    echo ""
}

# ── Show commits ─────────────────────────────────────────────────────────────
show_commits() {
    local base="$1" head="$2"
    local count
    count=$(git rev-list --count "$base".."$head" 2>/dev/null) || count=0

    if [[ "$count" -eq 0 ]]; then
        die "No commits to promote ($base is up to date with $head)"
    fi

    echo -e "${BOLD}Commits to promote ($count):${NC}"
    git log --oneline --no-decorate "$base".."$head" | head -30
    if [[ "$count" -gt 30 ]]; then
        dim "  ... and $((count - 30)) more"
    fi
    echo ""
}

# ── Modes ────────────────────────────────────────────────────────────────────
do_promote() {
    echo -e "${BOLD}Mode: Promote dev → main${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "dev"
    check_branch_sync "main"
    check_ci_passing "dev"
    echo ""

    show_commits "origin/main" "origin/dev"

    if $DRY_RUN; then
        info "Dry run complete — no changes made."
        return
    fi

    local branch="promote/$DATE"
    confirm "Create branch '$branch' and open PR to main?" || { echo "Aborted."; exit 0; }

    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/dev
    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Promote dev to main ($DATE)" \
        --body "$(cat <<EOF
## Summary
- Promotes current \`dev\` branch to \`main\`
- No version bump (code promotion only)

## Commits
$(git log --oneline origin/main..HEAD | head -20)
EOF
)")

    info "PR created: $pr_url"
    git checkout dev
}

do_release() {
    local current new_version
    current=$(read_version)
    new_version=$(calc_new_version "$current")

    echo -e "${BOLD}Mode: Release v$new_version${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "dev"
    check_branch_sync "main"
    check_ci_passing "dev"
    check_unreleased_content

    # Check tag doesn't exist
    if git rev-parse "v$new_version" &>/dev/null; then
        die "Tag v$new_version already exists"
    fi
    info "  Tag v$new_version is available"
    echo ""

    show_commits "origin/main" "origin/dev"

    echo -e "${BOLD}Version: $current → $new_version${NC}"
    preview_changelog "$new_version"

    if $DRY_RUN; then
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Create release branch, bump version, and open PR?" || { echo "Aborted."; exit 0; }

    local branch="release/v$new_version"
    CLEANUP_BRANCH="$branch"

    git checkout -b "$branch" origin/dev

    # Bump VERSION
    echo "$new_version" > VERSION

    # Stamp changelog
    stamp_changelog "$new_version" "$DATE"

    git add VERSION CHANGELOG.md
    git commit -m "bump version to $new_version"

    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Release v$new_version" \
        --label "release" \
        --body "$(cat <<EOF
## Summary
- Release **v$new_version** (was $current)
- Bumps VERSION and stamps CHANGELOG.md

## Changelog
$(awk -v ver="$new_version" '/^## \[/{if(found)exit} /^## \['"$new_version"'\]/{found=1} found{print}' CHANGELOG.md)

## Post-merge
Tag \`v$new_version\` will be created automatically, triggering Docker build + GitHub Release.
EOF
)")

    info "PR created: $pr_url"
    echo ""
    info "After merge:"
    info "  1. tag-release.yml auto-creates tag v$new_version"
    info "  2. docker-publish.yml builds + publishes Docker image"
    info "  3. GitHub Release + Discord notification"

    git checkout dev
}

do_cherry_pick() {
    echo -e "${BOLD}Mode: Cherry-pick to main${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "main"
    echo ""

    # Validate all SHAs exist
    for sha in "${CHERRY_SHAS[@]}"; do
        git cat-file -t "$sha" &>/dev/null \
            || die "Commit $sha not found"
        dim "  $(git log --oneline -1 "$sha")"
    done
    echo ""

    local branch new_version=""
    if [[ -n "$BUMP_TYPE" ]]; then
        local current
        current=$(read_version)
        new_version=$(calc_new_version "$current")
        branch="hotfix/v$new_version"
        echo -e "${BOLD}Version: $current → $new_version${NC}"
    else
        branch="hotfix/$DATE"
    fi

    if $DRY_RUN; then
        echo -e "Would create branch ${CYAN}$branch${NC} from origin/main"
        echo "Would cherry-pick: ${CHERRY_SHAS[*]}"
        [[ -n "$new_version" ]] && echo "Would bump version to $new_version"
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Cherry-pick ${#CHERRY_SHAS[@]} commit(s) to main via '$branch'?" || { echo "Aborted."; exit 0; }

    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/main

    for sha in "${CHERRY_SHAS[@]}"; do
        git cherry-pick "$sha" || die "Cherry-pick failed for $sha — resolve conflicts and retry"
    done

    if [[ -n "$new_version" ]]; then
        echo "$new_version" > VERSION
        if [[ -f CHANGELOG.md ]]; then
            stamp_changelog "$new_version" "$DATE"
            git add VERSION CHANGELOG.md
        else
            git add VERSION
        fi
        git commit -m "bump version to $new_version"
    fi

    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local title="Hotfix: cherry-pick to main"
    [[ -n "$new_version" ]] && title="Hotfix v$new_version"

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "$title" \
        --body "$(cat <<EOF
## Summary
Cherry-pick hotfix to main.

## Commits
$(for sha in "${CHERRY_SHAS[@]}"; do git log --oneline -1 "$sha"; done)
$(if [[ -n "$new_version" ]]; then echo -e "\n## Version\nBumped to **v$new_version**\n\nTag will be created automatically after merge."; fi)
EOF
)")

    info "PR created: $pr_url"
    git checkout dev
}

do_rollback() {
    echo -e "${BOLD}Mode: Rollback${NC}"
    echo "═══════════════════════════════════════"
    echo ""

    preflight
    check_branch_sync "main"
    echo ""

    # Determine which version to roll back
    local target_tag
    if [[ "$BUMP_TYPE" == "custom" && -n "$CUSTOM_VERSION" ]]; then
        target_tag="v$CUSTOM_VERSION"
        git rev-parse "$target_tag" &>/dev/null || die "Tag $target_tag not found"
    else
        target_tag=$(git describe --tags --abbrev=0 origin/main 2>/dev/null) \
            || die "No tags found on main"
    fi

    info "  Rolling back: $target_tag"

    # Find the merge commit for this tag on main
    local tag_sha merge_sha
    tag_sha=$(git rev-parse "$target_tag")

    # The tag points to a commit; find the merge commit on main that introduced it
    merge_sha=$(git log --merges --ancestry-path --oneline "${tag_sha}^..origin/main" \
        --format="%H" 2>/dev/null | tail -1)

    # If no merge commit found, the tag commit itself might be on main
    if [[ -z "$merge_sha" ]]; then
        # Check if the tagged commit is directly on main (fast-forward merge)
        if git merge-base --is-ancestor "$tag_sha" origin/main 2>/dev/null; then
            # Look for the most recent merge commit before the tag
            merge_sha=$(git log --merges --oneline origin/main --format="%H" \
                -1 --ancestry-path "$tag_sha^..origin/main" 2>/dev/null) || true
        fi
    fi

    # Last resort: try to find the merge commit that has the tag as a parent
    if [[ -z "$merge_sha" ]]; then
        merge_sha=$(git log --merges --oneline origin/main --format="%H" \
            --grep="release/$(echo "$target_tag" | sed 's/^v/v/')" 2>/dev/null | head -1) || true
    fi

    # If still nothing, use the tag commit itself
    if [[ -z "$merge_sha" ]]; then
        merge_sha="$tag_sha"
        warn "  Could not find merge commit — will revert the tagged commit directly"
    else
        info "  Merge commit: $(git log --oneline -1 "$merge_sha")"
    fi

    local branch="rollback/$target_tag"

    if $DRY_RUN; then
        echo -e "Would create branch ${CYAN}$branch${NC} from origin/main"
        echo "Would revert commit: $(git log --oneline -1 "$merge_sha")"
        info "Dry run complete — no changes made."
        return
    fi

    confirm "Revert $target_tag on main via '$branch'?" || { echo "Aborted."; exit 0; }

    CLEANUP_BRANCH="$branch"
    git checkout -b "$branch" origin/main

    # Revert — use -m 1 for merge commits, plain revert for non-merge
    if git cat-file -p "$merge_sha" | grep -q "^parent.*parent"; then
        git revert -m 1 --no-edit "$merge_sha"
    else
        git revert --no-edit "$merge_sha"
    fi

    git push -u origin "$branch"
    CLEANUP_BRANCH=""

    local pr_url
    pr_url=$(gh pr create \
        --base main \
        --head "$branch" \
        --title "Rollback $target_tag" \
        --body "$(cat <<EOF
## Summary
Reverts the release **$target_tag** on main.

## Reverted commit
\`$(git log --oneline -1 "$merge_sha")\`

## Follow-up
- [ ] Investigate the issue on \`dev\`
- [ ] Fix and create a new patch release when ready
EOF
)")

    info "PR created: $pr_url"
    echo ""
    warn "Remember: follow up with a patch release after fixing the issue on dev."
    git checkout dev
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
    # Ensure we're at the repo root
    cd "$(git rev-parse --show-toplevel)" || die "Not in a git repository"

    parse_args "$@"

    echo ""
    case "$MODE" in
        promote)     do_promote ;;
        release)     do_release ;;
        cherry-pick) do_cherry_pick ;;
        rollback)    do_rollback ;;
        *)           die "Unknown mode: $MODE" ;;
    esac
}

main "$@"
