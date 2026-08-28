#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
#
# Once this launch owns something to clean up, cleanup runs on every exit path:
# Ctrl+C (SIGINT), kill (SIGTERM), closing the terminal (SIGHUP), a startup step
# that fails, or either dev server exiting on its own.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# This checkout's ports, log paths and frontend API URLs. The main working tree
# keeps 8000/5173; linked worktrees get their own pair so several run at once.
. "$SCRIPT_DIR/dev-ports.sh"
cd "$SCRIPT_DIR/.."

BACKEND_PID=""
FRONTEND_PID=""
servers_started=false

# The guard makes the function idempotent so the signal path (trap fires, the
# poll loop below falls through, EXIT trap fires) and the natural-exit path (a
# server died, or a startup step failed under `set -e`) both end in exactly one
# cleanup pass.
cleanup_done=false
cleanup() {
    if [ "$cleanup_done" = true ]; then
        return 0
    fi
    cleanup_done=true
    echo
    if [ "$servers_started" = false ]; then
        # The seed ran but no server did, so the dev ports are still whoever
        # else's — take back only the data this launch put in the database.
        echo "Removing seeded dev data..."
        bash "$SCRIPT_DIR/dev-cleanup.sh" --data-only || true
        return 0
    fi
    echo "Stopping dev environment..."
    # Stop the servers this script started, then let dev-cleanup.sh sweep up
    # whatever is still on the ports and remove the seeded data.
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    bash "$SCRIPT_DIR/dev-cleanup.sh" || true
}

docker compose up db -d --wait
bash scripts/dev-migrate.sh

# Report a port that is already taken instead of taking it. Both dev servers
# bind a port this checkout owns, so anything already there belongs to someone
# else — another worktree's dev environment, most likely.
port_holder() {
    if command -v lsof &>/dev/null; then
        lsof -ti:"$1" 2>/dev/null | head -1
    elif command -v fuser &>/dev/null; then
        fuser "$1"/tcp 2>/dev/null | tr -d ' ' | head -1
    fi
}
for spec in "backend:$DEV_BACKEND_PORT" "frontend:$DEV_FRONTEND_PORT"; do
    holder=$(port_holder "${spec#*:}")
    if [ -n "$holder" ]; then
        echo "Port ${spec#*:} (${spec%%:*}) is already in use by pid $holder." >&2
        echo "Stop it, or pin this checkout elsewhere with DEV_BACKEND_PORT / DEV_FRONTEND_PORT." >&2
        exit 1
    fi
done

# Arm the teardown here rather than at the top of the script. Everything above
# is shared, idempotent setup that leaves nothing of ours running, and the dev
# ports and seeded data may still belong to another environment. From the seed
# onward this launch owns them, so every exit path below runs the cleanup.
trap cleanup INT TERM HUP EXIT

bash scripts/dev-seed.sh

# Spawning a server and recording its pid are two statements, and a signal
# landing between them would reach a cleanup that cannot see that server. Note
# the signal instead of acting on it, and let the check below run the teardown
# once both pids are recorded and the ports are known to be this launch's.
pending_signal=false
trap 'pending_signal=true' INT TERM HUP

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > "$DEV_BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Start the frontend in the background (Vite, port-cleanup built in). --open makes
# Vite open the app in the browser once it's listening; its `open` dependency is
# WSL-aware (launches the Windows browser) and handles macOS/Linux too.
nohup bash scripts/dev-frontend.sh --open > "$DEV_FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# Both servers are recorded, so the dev ports are now this launch's to sweep.
servers_started=true
trap cleanup INT TERM HUP

if [ "$pending_signal" = true ]; then
    exit 0
fi

echo
echo "Dev environment starting (checkout $DEV_CHECKOUT_ID):"
echo "  Backend:  http://localhost:$DEV_BACKEND_PORT   (logs: $DEV_BACKEND_LOG)"
echo "  Frontend: http://localhost:$DEV_FRONTEND_PORT   (logs: $DEV_FRONTEND_LOG)"
echo "  Stop:     press Ctrl+C in this terminal (or run bash scripts/dev-cleanup.sh)"
echo

# Block until a signal arrives or one of the servers exits. Poll rather than
# `wait`: plain `wait BACKEND_PID FRONTEND_PID` sits on the survivor when only
# one server goes down, so a backend that died at startup would leave the
# terminal blocked and the cleanup unrun, and `wait -n` (which returns on the
# first exit) needs bash 4.3+ — macOS still ships 3.2. `sleep` is interruptible,
# so a signal fires the trap above promptly. `set -e` is off from here so a
# server exiting non-zero doesn't bypass the trap on its way out.
set +e
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

# Ctrl+C reaches both servers, so both go down and there is nothing to explain.
# One down while the other is still up means that server fell over on its own —
# point at its log, since the environment is about to disappear either way. The
# pause lets the second server finish exiting before the two are told apart.
sleep 0.5
backend_up=false
frontend_up=false
kill -0 "$BACKEND_PID" 2>/dev/null && backend_up=true
kill -0 "$FRONTEND_PID" 2>/dev/null && frontend_up=true
if [ "$cleanup_done" = false ]; then
    if [ "$backend_up" = false ] && [ "$frontend_up" = true ]; then
        echo "Backend exited — see $DEV_BACKEND_LOG"
    elif [ "$frontend_up" = false ] && [ "$backend_up" = true ]; then
        echo "Frontend exited — see $DEV_FRONTEND_LOG"
    fi
fi
