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

if [ "$DEV_CHECKOUT_ID" = main ]; then
    DEV_PORT_OFFSET=0
else
    # 1..999: the offset has to stay clear of 0 (the main tree's) and keep both
    # ports inside a range nothing else here claims — 8001-8999 and 5174-6172.
    DEV_PORT_OFFSET=$(( (16#${DEV_CHECKOUT_ID:0:6} % 999) + 1 ))
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
