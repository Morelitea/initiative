#!/usr/bin/env bash
# Resolve this checkout's dev ports, log paths and frontend API URLs. Sourced by
# every dev script so they all agree on which ports belong to this worktree:
#
#   . "$SCRIPT_DIR/dev-ports.sh"
#
# The main working tree keeps the familiar 8000/5173. Linked worktrees — one per
# agent or branch — take an offset derived from their path, so several of them
# run side by side instead of taking the ports from each other. The path is used
# rather than the branch so the offset survives a rename or a branch switch.
#
# Set DEV_BACKEND_PORT / DEV_FRONTEND_PORT yourself to pin a checkout to
# particular ports; both are honoured if already set.

DEV_PORTS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# A linked worktree's git dir lives under the main checkout's .git/worktrees/;
# the main working tree's is the .git directory itself.
if [ -z "${DEV_CHECKOUT_ID:-}" ]; then
    if git -C "$DEV_PORTS_ROOT" rev-parse --git-dir >/dev/null 2>&1 &&
        [ "$(git -C "$DEV_PORTS_ROOT" rev-parse --git-dir)" != \
          "$(git -C "$DEV_PORTS_ROOT" rev-parse --git-common-dir)" ]; then
        DEV_CHECKOUT_ID="$(printf '%s' "$DEV_PORTS_ROOT" | sha256sum | cut -c1-8)"
    else
        DEV_CHECKOUT_ID=main
    fi
fi

# Offsets are handed out by a small registry rather than derived from the path.
# A digest would have to collide eventually — across a few dozen worktrees over
# any range that keeps the ports tidy it is likelier than not — and two
# checkouts landing on the same ports is the exact thing this file exists to
# prevent. The registry gives each checkout the lowest free offset and remembers
# it, so a checkout keeps its ports for as long as it exists.
DEV_PORTS_REGISTRY="${DEV_PORTS_REGISTRY:-${XDG_CACHE_HOME:-$HOME/.cache}/initiative/dev-ports}"

# Print this checkout's offset, allocating one if it has none. Fails (no output)
# rather than guessing if the registry can't be used.
_dev_ports_allocate() {
    local root="$1" lock offset waited=0 off path
    local kept=() taken=()

    mkdir -p "$(dirname "$DEV_PORTS_REGISTRY")" 2>/dev/null || return 1
    lock="$DEV_PORTS_REGISTRY.lock"

    # mkdir either creates the directory or fails, atomically, which makes it a
    # lock on every platform — flock isn't on macOS by default.
    until mkdir "$lock" 2>/dev/null; do
        waited=$((waited + 1))
        if [ "$waited" -gt 50 ]; then
            # Left behind by a run that was killed mid-allocation.
            rmdir "$lock" 2>/dev/null || return 1
            waited=0
        fi
        sleep 0.1
    done

    [ -f "$DEV_PORTS_REGISTRY" ] || : > "$DEV_PORTS_REGISTRY"
    while IFS=$'\t' read -r off path; do
        # Forget checkouts that have been deleted, so offsets stay small and
        # come back into use; a checkout that still exists keeps its ports even
        # while its dev environment is down.
        [ -n "$off" ] && [ -d "$path" ] || continue
        [ "$path" = "$root" ] && offset="$off"
        kept+=("$off	$path")
        taken+=("$off")
    done < "$DEV_PORTS_REGISTRY"

    if [ -z "${offset:-}" ]; then
        offset=1
        while printf '%s\n' "${taken[@]}" | grep -qx "$offset"; do
            offset=$((offset + 1))
        done
        kept+=("$offset	$root")
    fi

    printf '%s\n' "${kept[@]}" > "$DEV_PORTS_REGISTRY"
    rmdir "$lock" 2>/dev/null
    printf '%s' "$offset"
}

if [ "$DEV_CHECKOUT_ID" = main ]; then
    DEV_PORT_OFFSET=0
elif [ -z "${DEV_PORT_OFFSET:-}" ]; then
    DEV_PORT_OFFSET="$(_dev_ports_allocate "$DEV_PORTS_ROOT" || true)"
    if [ -z "$DEV_PORT_OFFSET" ]; then
        # No usable registry (read-only HOME, say). Fall back to a digest of the
        # path: stable and usually distinct, but it can collide — pre-launch says
        # so plainly if it does, and DEV_BACKEND_PORT/DEV_FRONTEND_PORT settle it.
        DEV_PORT_OFFSET=$(( (16#${DEV_CHECKOUT_ID:0:6} % 999) + 1 ))
    fi
fi

DEV_BACKEND_PORT="${DEV_BACKEND_PORT:-$((8000 + DEV_PORT_OFFSET))}"
DEV_FRONTEND_PORT="${DEV_FRONTEND_PORT:-$((5173 + DEV_PORT_OFFSET))}"

# Where the frontend reaches the backend. vite.config.ts reads
# VITE_DEV_PROXY_TARGET for its proxy, the SPA reads VITE_API_URL.
export VITE_DEV_PROXY_TARGET="${VITE_DEV_PROXY_TARGET:-http://localhost:${DEV_BACKEND_PORT}}"
export VITE_API_URL="${VITE_API_URL:-http://localhost:${DEV_BACKEND_PORT}/api/v1}"
export VITE_DEV_PORT="$DEV_FRONTEND_PORT"

# One log per checkout, so two dev environments don't write over each other.
DEV_BACKEND_LOG="/tmp/initiative-${DEV_CHECKOUT_ID}-backend.log"
DEV_FRONTEND_LOG="/tmp/initiative-${DEV_CHECKOUT_ID}-frontend.log"

export DEV_CHECKOUT_ID DEV_PORT_OFFSET DEV_BACKEND_PORT DEV_FRONTEND_PORT
export DEV_BACKEND_LOG DEV_FRONTEND_LOG
