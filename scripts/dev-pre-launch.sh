#!/usr/bin/env bash
# Orchestrate the dev environment startup chain. Equivalent of the VSCode dev:setup
# task chain: db -> migrate -> seed -> backend (bg) -> frontend (bg) -> browser.
#
# Once this launch owns something to clean up, cleanup runs on every exit path:
# Ctrl+C (SIGINT), kill (SIGTERM), closing the terminal (SIGHUP), a startup step
# that fails, or either dev server exiting on its own.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

# Arm the teardown here rather than at the top of the script. Everything above
# is shared, idempotent setup that leaves nothing of ours running, and the dev
# ports and seeded data may still belong to another environment. From the seed
# onward this launch owns them, so every exit path below runs the cleanup.
trap cleanup INT TERM HUP EXIT

bash scripts/dev-seed.sh

# Claim the dev ports before the first server is spawned, not after: a signal
# landing between the spawn and the assignment would otherwise reach a cleanup
# that skips both the pid and the port sweep, leaving that server behind. The
# cost the other way is a full sweep for a launch that got no further than here,
# which is the same sweep dev-backend.sh does to port 8000 on its way up.
servers_started=true

# Start the backend in the background (uvicorn with --reload, port-cleanup built in).
nohup bash scripts/dev-backend.sh > /tmp/initiative-backend.log 2>&1 &
BACKEND_PID=$!

# Start the frontend in the background (Vite, port-cleanup built in). --open makes
# Vite open the app in the browser once it's listening; its `open` dependency is
# WSL-aware (launches the Windows browser) and handles macOS/Linux too.
nohup bash scripts/dev-frontend.sh --open > /tmp/initiative-frontend.log 2>&1 &
FRONTEND_PID=$!

echo
echo "Dev environment starting:"
echo "  Backend:  http://localhost:8000   (logs: /tmp/initiative-backend.log)"
echo "  Frontend: http://localhost:5173   (logs: /tmp/initiative-frontend.log)"
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
        echo "Backend exited — see /tmp/initiative-backend.log"
    elif [ "$frontend_up" = false ] && [ "$backend_up" = true ]; then
        echo "Frontend exited — see /tmp/initiative-frontend.log"
    fi
fi
